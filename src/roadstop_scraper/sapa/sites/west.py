"""NEXCO西日本(w-holdings.co.jp)のSA/PAサイトアダプタ(タスク3.3)。

一覧の取得URL構成・パースと、詳細ページからの名称・路線名・上下線・方面・
住所・駐車場の抽出を実装する(design.md「sapa.sites」節参照)。

既知の制限(意図的なスコープ、タスク6.3の実サイト疎通確認でのフォローアップ
対象): 実測の結果、NEXCO西日本には一覧をサーバ側でHTMLレンダリングする
ページが存在しない(``/service_search/``・``/purpose_search/``のいずれも
詳細ページへのアンカーを含まない)。地図検索機能(``/map_search/``)がJavaScript
経由で単一のJSONエンドポイント(``sapa/json/map-search.json``)から全件を
読み込む構成であることを確認した(実測で310件)。このJSONを``HtmlPage``/
``parse_html``機構に通しても構造化データとしては解釈できない(``html.parser``
はJSONテキストから要素を復元できない)ため、``SapaSite``プロトコルを
``listing_kind``属性で拡張し、本サイトは``listing_kind = "json"``として
``parse_listing``に``HtmlPage``ではなく素の(``fetch_json``で得た)JSON値を
直接渡してもらう契約とした(``sapa/sites/__init__.py``のプロトコルdocstring
参照)。

east(1ページ目のみ返す限定なし)・central(1ページ目のみ返す既知の制限、
central.pyのモジュールdocstring参照)とは異なり、本サイトの一覧は
ページネーションを持たない。単一のJSON URLが310件全件を1回のフェッチで
返すため、``listing_urls``にはページ・件数の欠落は存在しない(central.pyの
「1ページ目のみ」制限とは対照的な性質であることを明示しておく)。

詳細ページの実測構造(美山パーキングエリア``https://www.w-holdings.co.jp/sapa/30020/``、
吉和サービスエリア``https://www.w-holdings.co.jp/sapa/09440/``、2施設で確認):
路線名は``p.p-sapa-heading-02__lead``のテキストにコード接頭辞なしでそのまま
入っている(east/centralと異なり"E1"等のコードは混在しない)。施設名は
``h1.p-sapa-heading-02__title``内の``<ruby>{name}<rt>{furigana}</rt></ruby>``
構造で提供され、``get_text()``をそのまま使うとふりがなが末尾に連結されて
しまうため、``<rt>``要素のテキストを別途取得し、末尾一致する場合のみ除去する
(3.3節、下記``_extract_name``参照)。上り/下りと方面は``_active``修飾クラス
(``.box-tag-02_active``/``.p-sapa-area-tag__text_active``)を持つ要素が
現在ページ自身の方向であり、非``_active``の要素は対向方向のクロスリンクで
あるため、必ず``_active``修飾クラス付きの要素のみを選択する。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import urlparse

from roadstop_scraper.geojson import Direction, Parking, Prefecture
from roadstop_scraper.sapa.address import split_postal_address
from roadstop_scraper.sapa.sites import SapaDetail, SapaListingResult, SapaStub
from roadstop_scraper.scraping.parser import HtmlPage

__all__ = ["WestSite"]

# 既知の制限(モジュールdocstring参照): 一覧の静的HTMLが存在しないため、
# 地図検索機能が参照する単一のJSONエンドポイントを一覧URLとして用いる。
# central.pyの「1ページ目のみ」制限とは異なり、このURL1件で全件(実測310件)を
# 取得できるためページネーションの欠落は無い。
_LISTING_JSON_URL = "https://www.w-holdings.co.jp/sapa/json/map-search.json"

_OWNED_HOSTS = frozenset({"w-holdings.co.jp", "www.w-holdings.co.jp"})

# NEXCO西日本の実管轄(近畿・中国・四国・九州沖縄、および中日本が管轄しない
# 中部隣接県)。east(1〜5)・central(_CENTRAL_PREFECTURE_CODES)いずれにも
# 含まれない都道府県コードの集合。
_WEST_PREFECTURE_CODES: frozenset[str] = frozenset(
    {
        "26",
        "27",
        "28",
        "29",
        "30",  # 近畿: 京都・大阪・兵庫・奈良・和歌山
        "31",
        "32",
        "33",
        "34",
        "35",  # 中国: 鳥取・島根・岡山・広島・山口
        "36",
        "37",
        "38",
        "39",  # 四国: 徳島・香川・愛媛・高知
        "40",
        "41",
        "42",
        "43",
        "44",
        "45",
        "46",
        "47",  # 九州・沖縄
    }
)

# 詳細ページ セレクタ(実測、モジュールdocstring参照)。
_ROAD_SELECTOR = "p.p-sapa-heading-02__lead"
_NAME_SELECTOR = "h1.p-sapa-heading-02__title"
_FURIGANA_SELECTOR = "h1.p-sapa-heading-02__title rt"
# 対向方向(現在ページの反対方向)は``_active``修飾クラスを持たない要素。
# 現在ページ自身の方向は``_active``修飾クラス付きの要素からのみ取得する。
_ACTIVE_DIRECTION_SELECTOR = ".box-tag-02_active"
_ACTIVE_AREA_DIRECTION_SELECTOR = ".p-sapa-area-tag__text_active"
_LABEL_SELECTOR = ".box-facility-info__list-head"
_VALUE_SELECTOR = ".box-facility-info__list-text"

_LABEL_ADDRESS = "住所"
_LABEL_PARKING = "パーキング"

# 駐車場: 「【大型】5 【小型】10 【兼用】0 …」形式。他サイトの「大型：132」
# 「大型　148」とは異なる新しい括弧+空白区切りの表記のため専用の正規表現を書く。
_PARKING_LARGE_PATTERN = re.compile(r"【大型】\s*(\d+)")
_PARKING_STANDARD_PATTERN = re.compile(r"【小型】\s*(\d+)")

# 上り/下りは裸の完全一致でのみ受理する(east.pyと同じ方針。「内回り」等の
# Directionに存在しない区分は方向不明としてNoneへ写像する)。
_UP_MARKER = "上り"
_DOWN_MARKER = "下り"


class WestSite:
    """NEXCO西日本(w-holdings.co.jp)のSA/PAサイトアダプタ。"""

    key = "west"
    listing_kind = "json"

    def owns_url(self, url: str) -> bool:
        """``url``のホスト名がw-holdings.co.jp系かどうかを判定する。"""
        return urlparse(url).hostname in _OWNED_HOSTS

    def listing_urls(self, prefectures: Sequence[Prefecture]) -> tuple[str, ...]:
        """対象都道府県列がNEXCO西日本管内と交差する場合、JSONエンドポイントのURLを返す。

        いずれとも交差しない場合は空タプル。他サイトと異なりページネーションが
        無いため、返す場合は常に高々1件(モジュールdocstring参照)。
        """
        requested_codes = {prefecture.code for prefecture in prefectures}
        if requested_codes.intersection(_WEST_PREFECTURE_CODES):
            return (_LISTING_JSON_URL,)
        return ()

    def parse_listing(self, content: object) -> SapaListingResult:
        """一覧JSON(``list[dict]``)の各要素からスタブ列を抽出する。

        ``content``は(将来の)collectorが``fetch_json``で取得した生のJSON値
        であり、``HtmlPage``ではない(本サイトの``listing_kind == "json"``)。
        外部由来の未検証データのため、``content``自体がリストでない場合・
        要素が辞書でない場合・キーが欠落/空文字の場合のいずれも例外を送出せず
        スキップとして扱う(``sapa/geocoding.py``の防御的パースの方針に倣う)。

        ``sa_pa_short``・``url``のいずれかが欠落/空文字の要素はスキップする
        (``skipped_count``を加算)が、``url``自体が解釈できた場合は
        ``listed_urls``に残す(east.py/central.pyの前例と同じ「URLが取れれば
        一覧に実在した事実を残す」規律)。``url``は実測で既に絶対URLのため
        ``urljoin``は行わずそのまま使う。
        """
        if not isinstance(content, list):
            return SapaListingResult(stubs=(), listed_urls=frozenset(), skipped_count=0)

        stubs: list[SapaStub] = []
        listed_urls: set[str] = set()
        skipped_count = 0

        for record in content:
            if not isinstance(record, dict):
                skipped_count += 1
                continue

            name = _extract_nonempty_str(record, "sa_pa_short")
            detail_url = _extract_nonempty_str(record, "url")

            if detail_url is not None:
                listed_urls.add(detail_url)

            if name is None or detail_url is None:
                skipped_count += 1
                continue

            stubs.append(SapaStub(display_name=name, detail_url=detail_url))

        return SapaListingResult(
            stubs=tuple(stubs),
            listed_urls=frozenset(listed_urls),
            skipped_count=skipped_count,
        )

    def extract_detail(self, page: HtmlPage, detail_url: str) -> SapaDetail:
        """詳細ページから``SapaDetail``を抽出する。

        ``detail_url``引数はこのアダプタでは抽出に用いない(collector側で管理、
        east.py/central.pyと同じ前例)。名称を解決できない場合は、
        ``HtmlPage.require_text``の自然な送出により``StructureChangedError``
        となる。

        ``coordinate``は常に``None``を返す(既知の制限。CONCERNS参照: 本サイトの
        JSON一覧には直接座標(``latitude``/``longitude``)が含まれるが、現行の
        ``SapaListingResult``/``SapaStub``の形状(タスク2.3で確定、
        ``display_name``+``detail_url``のみ)にはそれを``extract_detail``まで
        引き継ぐ手段が無いため、本タスクの範囲では詳細HTMLからの取得のみを
        行う)。tel・opening_hours・websitesはこのサイトの実測では確認できて
        いないため常にNone/空のまま返す。
        """
        del detail_url

        name = _extract_name(page)
        if not name:
            page.require_text(_NAME_SELECTOR)

        road_name = page.find_text(_ROAD_SELECTOR)
        direction = _parse_bare_direction(page.find_text(_ACTIVE_DIRECTION_SELECTOR))
        area_direction = page.find_text(_ACTIVE_AREA_DIRECTION_SELECTOR) or None

        labels = page.find_texts(_LABEL_SELECTOR)
        values = page.find_texts(_VALUE_SELECTOR)
        fields = dict(zip(labels, values, strict=False))

        address, postal_code = _split_address(fields.get(_LABEL_ADDRESS))

        return SapaDetail(
            name=name,
            road_name=road_name,
            direction=direction,
            area_direction=area_direction,
            address=address,
            postal_code=postal_code,
            tel=None,
            opening_hours=None,
            parking=_parse_parking(fields.get(_LABEL_PARKING)),
            websites=(),
            facilities=(),
            coordinate=None,
        )


def _extract_nonempty_str(record: dict[str, object], key: str) -> str | None:
    """辞書``record``から``key``の値を取り出し、非空文字列であれば返す。

    外部由来の未検証JSONのため、キー欠落・非文字列型・空文字列のいずれも
    ``None``として扱い、呼び出し側でスキップ判定できるようにする。
    """
    value = record.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _extract_name(page: HtmlPage) -> str | None:
    """``<ruby>{name}<rt>{furigana}</rt></ruby>``構造からふりがなを除いた名称を返す。

    ``h1.p-sapa-heading-02__title``の``get_text()``は``<rt>``のふりがな
    テキストを末尾に連結してしまう(例:``"美山パーキングエリアみやま"``)ため、
    ``<rt>``要素のテキストを別途取得し、末尾一致する場合のみ除去する。
    ``<rt>``が存在しない、または末尾一致しない場合はそのままのテキストを返す
    (構造が想定と異なる場合でも例外は送出せず、後続の``require_text``による
    構造変化検知に委ねる)。
    """
    full = page.find_text(_NAME_SELECTOR)
    if not full:
        return None

    furigana = page.find_text(_FURIGANA_SELECTOR)
    if furigana and full.endswith(furigana):
        stripped = full[: -len(furigana)].strip()
        if stripped:
            return stripped

    return full


def _split_address(raw: str | None) -> tuple[str | None, str | None]:
    """住所生文字列を(住所本体, 郵便番号)へ分離する。値自体が無ければ両方None。

    このサイトの実測住所には郵便番号(〒)が含まれないが、``split_postal_address``
    は一致しない場合``(None, raw)``を返す契約のため、そのまま委譲してよい。
    """
    if raw is None:
        return None, None
    postal_code, address = split_postal_address(raw)
    return address, postal_code


def _parse_parking(value: str | None) -> Parking | None:
    """駐車場テキストを大型・普通車の台数へ分解する(小型→standardへの写像)。

    キー自体が無ければNoneを返す。身障者用の区分はこのサイトの実測では
    「障がい者用大型」「障がい者用小型」に分かれており、``Parking.disabled``
    (単一区分)へ一意に写像できないため、他アダプタと同様に確認できた区分
    (大型・小型)のみ抽出し、常にNoneのままとする。
    """
    if value is None:
        return None
    return Parking(
        large=_search_int(_PARKING_LARGE_PATTERN, value),
        standard=_search_int(_PARKING_STANDARD_PATTERN, value),
    )


def _search_int(pattern: re.Pattern[str], value: str) -> int | None:
    match = pattern.search(value)
    if match is None:
        return None
    return int(match.group(1))


def _parse_bare_direction(text: str | None) -> Direction | None:
    """裸の(括弧・接尾辞なしの)上り/下り表記のみをDirectionへ写像する。

    「内回り」等、Directionに存在しない区分やその他の非対応表記は上り/下り
    いずれとも完全一致しないため、意図どおりNoneへ写像される(east.pyと同じ
    方針)。
    """
    if text == _UP_MARKER:
        return Direction.UP
    if text == _DOWN_MARKER:
        return Direction.DOWN
    return None
