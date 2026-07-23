"""NEXCO東日本(driveplaza.com)のSA/PAサイトアダプタ(タスク3.1)。

対象エリア・道路の一覧URL構成、一覧からのスタブ抽出、詳細ページからの
名称・路線名・上下線・住所等の抽出を実装する(design.md「sapa.sites」節参照)。

既知の制限(タスク6.3の実サイト疎通確認で確認、修正不可能な実サイトの制約):
一覧ページ(``https://www.driveplaza.com/dp/SAPAServRes``)は「NEXCO東日本管内の
サービスエリアのみ検索可能」だが、検索フォームの``arealist``パラメータは
``HIGHWAY=AA``と併用した場合、値によらず常に東日本管内全域(実測約875件、
北海道から北陸まで)を返すことをcurlによるライブ検証で確認した
(``arealist=0``と``arealist=1``が完全に同一のレスポンスを返す。``HIGHWAY``の
指定自体は必須だが値は結果に影響しない)。つまり``arealist``による一覧の
サーバ側絞り込みは実質的に機能していない。この絞り込みが実際にどのような
機構(JS駆動のフォーム送信等)で行われているかは静的なGETリクエストでは
再現できず、都道府県単位の一覧フィルタは実サイト側に存在しないと結論づけた。
そのため``listing_urls``は要求都道府県が東日本管内(北海道〜北陸)と1件でも
交差する限り、常に単一の全域一覧URL(``arealist=0``)のみを返す。都道府県への
絞り込みは一覧取得の時点では行わず、``sapa.collector``が各施設の住所から
導出した都道府県によって完全に担う(collector側の既存ロジックで対応済み、
本アダプタの変更は不要)。以前は``arealist``値ごとに複数のURLを構成していたが、
これらは互いに重複する同一内容の再取得に過ぎず、サードパーティサーバへの
不要な負荷だったため単一URLへ整理した。

詳細ページには実測で2種類のテンプレートが確認されている:
「標準」テンプレート(``h1.c-titleH1``に施設名、``span.c-labelRight``に上り/下りの
裸の表記)と「Pasar」ブランドの旗艦施設向けテンプレート(``div.cont_information-text
h2``に「施設名・方向」表記)。両テンプレートを順に試し、いずれからも名称を解決
できない場合のみ構造変化として扱う(``HtmlPage.require_text``の自然な送出に委ねる)。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import urljoin, urlparse, urlunparse

from roadstop_scraper.geojson import Direction, Parking, Prefecture
from roadstop_scraper.sapa.address import split_postal_address
from roadstop_scraper.sapa.sites import SapaDetail, SapaListingResult, SapaStub
from roadstop_scraper.scraping.parser import HtmlPage

__all__ = ["EastSite"]

_LISTING_URL_TEMPLATE = "https://www.driveplaza.com/dp/SAPAServRes?arealist={arealist}&HIGHWAY=AA"

# NEXCO東日本管内に該当する都道府県コード(北海道・東北・関東・信越・北陸の
# 全都道府県の和集合)。モジュールdocstring記載のとおり、arealistの値は
# 一覧の絞り込みには寄与しない(常に東日本管内全域が返る)ため、ここでは
# 「東日本管内かどうか」の判定にのみ用いる単純な集合とする
# (central.py/west.pyの``_CENTRAL_PREFECTURE_CODES``/``_WEST_PREFECTURE_CODES``と
# 同じ平坦集合の規約に倣う)。
_EAST_PREFECTURE_CODES: frozenset[str] = frozenset(
    {
        "01",  # 北海道
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",  # 東北
        "08",
        "09",
        "10",
        "11",
        "12",
        "13",
        "14",  # 関東
        "15",
        "20",  # 信越(新潟・長野)
        "16",
        "17",
        "18",  # 北陸(富山・石川・福井)
    }
)

_OWNED_HOSTS = frozenset({"driveplaza.com", "www.driveplaza.com"})

# 一覧ページ: div.box-sapaごとに1件の施設(実測、research.md参照)。
_LISTING_ITEM_SELECTOR = "div.box-sapa"
_LISTING_NAME_SELECTOR = f"{_LISTING_ITEM_SELECTOR} h3.ttl-sapaName a"

# 詳細ページ テンプレートA(標準)。
_NAME_A_SELECTOR = "h1.c-titleH1 .txt-title"
_ROAD_A_SELECTOR = "span.txt-way"
_DIRECTION_A_SELECTOR = "span.c-labelRight"
_ADDRESS_A_SELECTOR = "div.box-facility div.box-info p"
_LABEL_A_SELECTOR = "dl.li-info dt"
_VALUE_A_SELECTOR = "dl.li-info dd"

# 詳細ページ テンプレートB(Pasarブランド)。
_HEADING_B_SELECTOR = "div.cont_information-text h2"
_ADDRESS_B_SELECTOR = "div.cont_information-text p"
_TITLE_SELECTOR = "title"
_PARK_LABEL_B_SELECTOR = "dl.cont_information-park dt"
_PARK_VALUE_B_SELECTOR = "dl.cont_information-park dd"
_INFO_LABEL_B_SELECTOR = "dl.cont_information-info dt"
_INFO_VALUE_B_SELECTOR = "dl.cont_information-info dd"

_LABEL_PARKING = "駐車場"
_LABEL_OPENING_HOURS_B = "サービスエリア・コンシェルジェ"

# 駐車場ddは「大型：132／小型：354」(一覧・テンプレートB)と
# 「大型　148 ／ 小型　114」(テンプレートA、全角空白区切り)の両表記がある
# ため、ラベルと数字の間の区切りとして「：」と空白(全角含む)の両方を許容する。
_PARKING_LARGE_PATTERN = re.compile(r"大型[：\s]+(\d+)")
_PARKING_STANDARD_PATTERN = re.compile(r"小型[：\s]+(\d+)")

# 上り/下りは裸の完全一致でのみ受理する(「内回り」「外回り」等、Directionに
# 存在しない区分は方向不明としてNoneへ写像する)。
_UP_MARKER = "上り"
_DOWN_MARKER = "下り"


class EastSite:
    """NEXCO東日本(ドラぷら/driveplaza.com)のSA/PAサイトアダプタ。"""

    key = "east"
    listing_kind = "html"

    def owns_url(self, url: str) -> bool:
        """``url``のホスト名がdriveplaza.com系かどうかを判定する。"""
        return urlparse(url).hostname in _OWNED_HOSTS

    def listing_urls(self, prefectures: Sequence[Prefecture]) -> tuple[str, ...]:
        """対象都道府県列がNEXCO東日本管内と交差する場合、単一の一覧URLを返す。

        モジュールdocstring記載のとおり``arealist``は一覧の絞り込みには寄与
        しない(値によらず東日本管内全域・実測約875件が返る)ため、要求都道府県
        がいずれか1件でも東日本管内(北海道〜北陸)と交差すれば、常に高々1件
        (``arealist=0``の全域URL)を返す。都道府県ごとに複数のURLを構成しても
        全て同一内容の重複取得になるだけで、サードパーティサーバへの不要な
        負荷にしかならないため、意図的に単一URLへ集約している。

        いずれの都道府県とも交差しない場合(九州のみ等)は空タプルを返す。これは
        NEXCO東日本が単に当該地域に施設を持たないという正当な結果であり、
        呼び出し側(collector)は当該サイトから0件のスタブを得るだけでよい。
        """
        requested_codes = {prefecture.code for prefecture in prefectures}
        if requested_codes.intersection(_EAST_PREFECTURE_CODES):
            return (_LISTING_URL_TEMPLATE.format(arealist=0),)
        return ()

    def parse_listing(self, page: HtmlPage) -> SapaListingResult:
        """一覧ページの``div.box-sapa``要素群からスタブ列を抽出する。

        名称・詳細URLとも同一セレクタ(``h3.ttl-sapaName a``)から取得するため、
        ``find_texts``/``find_attrs``は常に同じ件数・同じDOM順で対応する。
        名称が空、または詳細URLが解釈できない要素はスキップするが、詳細URLが
        解釈できた分は``listed_urls``に残す(michinoeki/listing.pyの「url確認
        できたがstub化できない要素もlisted_urlsに残す」precedentに倣う)。
        """
        names = page.find_texts(_LISTING_NAME_SELECTOR)
        hrefs = page.find_attrs(_LISTING_NAME_SELECTOR, "href")

        stubs: list[SapaStub] = []
        listed_urls: set[str] = set()
        skipped_count = 0

        for name, href in zip(names, hrefs, strict=True):
            detail_url = _normalize_detail_url(page.url, href) if href else None

            if detail_url is None or not name:
                skipped_count += 1
                if detail_url:
                    listed_urls.add(detail_url)
                continue

            listed_urls.add(detail_url)
            stubs.append(SapaStub(display_name=name, detail_url=detail_url))

        return SapaListingResult(
            stubs=tuple(stubs),
            listed_urls=frozenset(listed_urls),
            skipped_count=skipped_count,
        )

    def extract_detail(self, page: HtmlPage, detail_url: str) -> SapaDetail:
        """詳細ページをテンプレートA→Bの順に試みて``SapaDetail``へ変換する。

        ``detail_url``引数はこのアダプタでは抽出に用いない(名称・URLの対応は
        collector側で管理されるため)。いずれのテンプレートからも名称を解決
        できない場合は、テンプレートAの必須セレクタに対する``require_text``の
        自然な送出により``StructureChangedError``となる。
        """
        del detail_url

        name_a = page.find_text(_NAME_A_SELECTOR)
        if name_a:
            return self._extract_template_a(page, name_a)

        heading_b = page.find_text(_HEADING_B_SELECTOR)
        if heading_b:
            return self._extract_template_b(page, heading_b)

        # いずれのテンプレートでも名称を解決できない: 構造変化として扱う。
        # name_a・heading_bともに既にNone/空文字であることを確認済みのため、
        # require_textは必ずStructureChangedErrorを送出する。
        page.require_text(_NAME_A_SELECTOR)

    def _extract_template_a(self, page: HtmlPage, name: str) -> SapaDetail:
        road_name = page.find_text(_ROAD_A_SELECTOR)
        direction = _parse_bare_direction(page.find_text(_DIRECTION_A_SELECTOR))
        address, postal_code = _split_address(page.find_text(_ADDRESS_A_SELECTOR))

        labels = page.find_texts(_LABEL_A_SELECTOR)
        values = page.find_texts(_VALUE_A_SELECTOR)
        fields = dict(zip(labels, values, strict=False))

        return SapaDetail(
            name=name,
            road_name=road_name,
            direction=direction,
            area_direction=None,
            address=address,
            postal_code=postal_code,
            tel=None,
            opening_hours=None,
            parking=_parse_parking(fields.get(_LABEL_PARKING)),
            websites=(),
            facilities=(),
            coordinate=None,
        )

    def _extract_template_b(self, page: HtmlPage, heading: str) -> SapaDetail:
        before, sep, after = heading.rpartition("・")
        name = before if sep else heading
        direction_text = after if sep else None

        road_name = _extract_road_name_from_title(page.find_text(_TITLE_SELECTOR))
        direction = _parse_bare_direction(direction_text)
        address, postal_code = _split_address(page.find_text(_ADDRESS_B_SELECTOR))

        park_labels = page.find_texts(_PARK_LABEL_B_SELECTOR)
        park_values = page.find_texts(_PARK_VALUE_B_SELECTOR)
        park_fields = dict(zip(park_labels, park_values, strict=False))

        info_labels = page.find_texts(_INFO_LABEL_B_SELECTOR)
        info_values = page.find_texts(_INFO_VALUE_B_SELECTOR)
        info_fields = dict(zip(info_labels, info_values, strict=False))

        return SapaDetail(
            name=name,
            road_name=road_name,
            direction=direction,
            area_direction=None,
            address=address,
            postal_code=postal_code,
            tel=None,
            opening_hours=info_fields.get(_LABEL_OPENING_HOURS_B),
            parking=_parse_parking(park_fields.get(_LABEL_PARKING)),
            websites=(),
            facilities=(),
            coordinate=None,
        )


def _normalize_detail_url(base_url: str, href: str) -> str:
    """相対URLを一覧ページ基準で絶対化し、schemeを``https``へ正規化する。

    実測では``h3.ttl-sapaName a``の``href``は既に絶対URLだが``http://``表記
    (実際は``https://``へ301リダイレクトされる)であるため、同一施設が
    scheme表記の揺れによらず同一のマージ・レジュームキーになるよう正規化する。
    """
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    return urlunparse(parsed._replace(scheme="https"))


def _split_address(raw: str | None) -> tuple[str | None, str | None]:
    """住所生文字列を(住所本体, 郵便番号)へ分離する。値自体が無ければ両方None。"""
    if raw is None:
        return None, None
    postal_code, address = split_postal_address(raw)
    return address, postal_code


def _parse_parking(value: str | None) -> Parking | None:
    """駐車場ddを大型・普通車の台数へ分解する(小型→standardへの写像)。

    キー自体が無ければNoneを返す。身障者用の区分はこのサイトの実測では
    確認できていないため常にNoneのままとする。
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

    「内回り」「外回り」等、Directionに存在しない区分やその他の非対応表記は
    上り/下りいずれとも完全一致しないため、意図どおりNoneへ写像される
    (誤ってUP/DOWNへ丸め込まない)。
    """
    if text == _UP_MARKER:
        return Direction.UP
    if text == _DOWN_MARKER:
        return Direction.DOWN
    return None


def _extract_road_name_from_title(title: str | None) -> str | None:
    """テンプレートBの``<title>``から路線名を導出する。

    ``"Pasar ( パサール ) Pasar蓮田(上り線)・東北自動車道 | サービスエリア | ドラぷら"``
    のように、``" | "``以降を除いた残りを最後の「・」で分割した後半が路線名になる
    (研究時に一覧ページの``span.txt-road``値と独立に一致することを確認済み)。
    """
    if title is None:
        return None
    head = title.split(" | ", 1)[0]
    _before, sep, after = head.rpartition("・")
    if not sep:
        return None
    return after or None
