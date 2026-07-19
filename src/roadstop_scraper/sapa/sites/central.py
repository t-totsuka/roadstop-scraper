"""NEXCO中日本(sapa.c-nexco.co.jp)のSA/PAサイトアダプタ(タスク3.2)。

一覧ページの取得URL構成・パースと、詳細ページからの名称・路線名・上下線・
方面・住所・駐車場・座標の抽出を実装する(design.md「sapa.sites」節参照)。

既知の制限(意図的なスコープ、タスク6.3の実サイト疎通確認でのフォローアップ
対象): 一覧ページ(``https://sapa.c-nexco.co.jp/search/result``)は216件を
20件ずつ返すページネーションを持つが、そのページ送りは
``onclick="paging(this, 'sapa-oposite-form', '/search/Page', 'page')"``という
JS駆動の仕組みで、``/search/Page?PageNum=2``・``/search/result?PageNum=2``への
直接アクセス(GET/POST)を試みたが、いずれもページ1へのリダイレクト・404・
ページ1内容の再返却のいずれかとなり、静的な解析だけでは再現できなかった
(実測はレート制限を適用した最小限のアクセスに留めている)。そのため
``listing_urls``は1ページ目(216件中20件)のみを返す。未検証のページネーション
URLパターンを推測で実装することは行わない(推測が外れて1ページ目の内容を
無言で返し続けた場合、196件を無言で欠落させたまま「動いているように見える」
状態になり、正しく1ページのみに限定するより有害であるため)。ブラウザの
開発者ツールでのネットワーク調査によるページネーション機構の解明は
タスク6.3以降のフォローアップ課題とする。

一覧ページには同一データがモバイル用テーブル(``div#page_sp``、行は
``tr.tableTr-SP``)とデスクトップ用テーブル(``div#page``、行は``tr.tableTr``)の
2箇所にレンダリングされている(レスポンシブCSSによる重複であり、追加データ
ではない)。二重カウントを避けるため``div#page``配下のみを対象とする。

詳細ページの上り/下り表記は「港北PA（上り：東京方面）」のように名称・方向・
方面の3要素が1つの見出し(``h3.heading``)に複合表記される、一覧ページの単純な
「（上り）」/「（下り）」とは異なる形式のため、共通ヘルパ
(``normalize_direction``/``strip_direction_notation``)では方面を分離できない。
この複合形式は``central.py``内のローカル正規表現で解析する(3.1の東日本アダプタ
が裸表記「上り」「下り」向けにローカルヘルパを実装した前例に倣う)。なお
一覧ページの「（上り）」/「（下り）」形式自体は共通ヘルパが対応済み
(``tests/sapa/sites/test_common.py``で全角括弧込みの表記が検証されている)
だが、``SapaStub.display_name``は生の表示名を保持する契約(east.pyの前例と
同様)のため、一覧パース時点では共通ヘルパを呼び出さない。
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from urllib.parse import urljoin, urlparse

from roadstop_scraper.geojson import Coordinate, Direction, Parking, Prefecture
from roadstop_scraper.sapa.address import split_postal_address
from roadstop_scraper.sapa.sites import (
    SapaDetail,
    SapaListingResult,
    SapaStub,
    normalize_direction,
    strip_direction_notation,
)
from roadstop_scraper.scraping.parser import HtmlPage

__all__ = ["CentralSite"]

_OWNED_HOST = "sapa.c-nexco.co.jp"

# 既知の制限(モジュールdocstring参照): ページネーションを再現できないため
# 1ページ目(216件中20件)のみを返す。
_SEARCH_RESULT_URL = "https://sapa.c-nexco.co.jp/search/result"

# NEXCO中日本の実管轄(公開情報に基づく、東海地方+近畿の一部)。
_CENTRAL_PREFECTURE_CODES: frozenset[str] = frozenset(
    {
        "15",  # 新潟県
        "16",  # 富山県
        "17",  # 石川県
        "18",  # 福井県
        "19",  # 山梨県
        "20",  # 長野県
        "21",  # 岐阜県
        "22",  # 静岡県
        "23",  # 愛知県
        "24",  # 三重県
        "25",  # 滋賀県
    }
)

# 一覧ページ: div#page(デスクトップ用テーブル)配下のtr.tableTrのみを対象とする
# (div#page_spはモバイル用の重複描画のため対象外)。ヘッダ行は<th>のみで<td>を
# 持たないため、"td:nth-child(2)"はヘッダ行には一致しない(実測確認済み)。
# 名称・詳細URLは同一のa要素から取得するため、find_texts/find_attrsの件数は
# 常に一致する(east.pyと同じ前例)。
_LISTING_LINK_SELECTOR = "div#page tr.tableTr td:nth-child(2) a"

# 詳細ページ: .sapa_summary(サイドバー)ブロックを一次情報源とする。
_HEADING_SELECTOR = ".sapa_summary h3.heading"
_ROAD_PARAGRAPH_SELECTOR = ".sapa_summary p"
_ADDRESS_SELECTOR = ".sapa_summary p.address"
_PARKING_SELECTOR = ".sapa_summary p.ico-parking"
# GoogleマップリンクはPage内のどこにあってもよいためスコープしない。
_MAP_LINK_SELECTOR = 'a[href*="google.com/maps"]'

# 路線コードトークン(例: "E1")の判定。短い英数字のみのトークンを路線コードと
# みなし、路線名本体から除去する。
_ROUTE_CODE_TOKEN_PATTERN = re.compile(r"^[A-Z0-9]{1,5}$")

# 詳細ページ見出しの複合表記「港北PA（上り：東京方面）」を解析する。
# 一覧ページの単純な「（上り）」形式とは異なり方面を含む3要素構成のため、
# 共通ヘルパでは解析できずここでローカルに解析する。
_HEADING_COMPOUND_PATTERN = re.compile(r"^(?P<name>.+?)[（(](?P<direction>上り|下り)：(?P<area_direction>.+)[）)]$")

# 駐車場: 「大型：25/小型：68（大型との兼用を含む）」形式。区切りは半角スラッシュ、
# ラベルと数字の区切りは全角コロン(他サイトと共通)。
_PARKING_LARGE_PATTERN = re.compile(r"大型：(\d+)")
_PARKING_STANDARD_PATTERN = re.compile(r"小型：(\d+)")

# Googleマップリンクの座標抽出: "@{lat},{lon},{zoom}"の順(GeoJSONの[lon,lat]とは逆順)。
_MAP_COORDINATE_PATTERN = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+),")


class CentralSite:
    """NEXCO中日本(sapa.c-nexco.co.jp)のSA/PAサイトアダプタ。"""

    key = "central"

    def owns_url(self, url: str) -> bool:
        """``url``のホスト名が``sapa.c-nexco.co.jp``と完全一致するかを判定する。"""
        return urlparse(url).hostname == _OWNED_HOST

    def listing_urls(self, prefectures: Sequence[Prefecture]) -> tuple[str, ...]:
        """対象都道府県列がNEXCO中日本管内と交差する場合、一覧URL(1ページ目のみ)を返す。

        モジュールdocstring記載の既知の制限により、常に高々1件(1ページ目、
        216件中20件)を返す。いずれの都道府県とも交差しない場合は空タプル。
        """
        requested_codes = {prefecture.code for prefecture in prefectures}
        if requested_codes.intersection(_CENTRAL_PREFECTURE_CODES):
            return (_SEARCH_RESULT_URL,)
        return ()

    def parse_listing(self, page: HtmlPage) -> SapaListingResult:
        """``div#page tr.tableTr``の各行からスタブ列を抽出する。

        本メソッド自体はページネーションに依存しない(渡された``page``が
        何ページ目であってもそのまま同じロジックでパースできる)。呼び出し側
        (将来のcollector)が複数ページ分の``SapaListingResult``を集約する
        ことで複数ページに対応できる設計だが、``listing_urls``自体は現状
        1ページ目のみを返す(モジュールdocstring参照)。

        名称・詳細URLとも同一セレクタ(``td:nth-child(2) a``)から取得するため、
        ``find_texts``/``find_attrs``は常に同じ件数・同じDOM順で対応する。
        名称が空、または詳細URL(``/sapa?sapainfoid=N``)が解釈できない要素は
        スキップするが、詳細URLが解釈できた分は``listed_urls``に残す
        (michinoeki/listing.py・east.pyの前例に倣う)。
        """
        names = page.find_texts(_LISTING_LINK_SELECTOR)
        hrefs = page.find_attrs(_LISTING_LINK_SELECTOR, "href")

        stubs: list[SapaStub] = []
        listed_urls: set[str] = set()
        skipped_count = 0

        for name, href in zip(names, hrefs, strict=True):
            detail_url = urljoin(page.url, href) if href else None

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
        """詳細ページ(``.sapa_summary``ブロック)から``SapaDetail``を抽出する。

        ``detail_url``引数はこのアダプタでは抽出に用いない(collector側で管理)。
        見出し(``h3.heading``)から名称を解決できない場合は、``require_text``の
        自然な送出により``StructureChangedError``となる(east.pyと同じ前例)。

        tel・opening_hours・websites・facilitiesは実測で確認できていないため
        None/空のまま返す(3.3「対象サイトで提供されている場合に抽出」)。
        """
        del detail_url

        heading = page.require_text(_HEADING_SELECTOR)
        name, direction, area_direction = _parse_heading(heading)

        road_paragraphs = page.find_texts(_ROAD_PARAGRAPH_SELECTOR)
        road_name = _parse_road_name(road_paragraphs[0]) if road_paragraphs else None

        address, postal_code = _split_address(page.find_text(_ADDRESS_SELECTOR))
        parking = _parse_parking(page.find_text(_PARKING_SELECTOR))
        coordinate = _parse_coordinate(page)

        return SapaDetail(
            name=name,
            road_name=road_name,
            direction=direction,
            area_direction=area_direction,
            address=address,
            postal_code=postal_code,
            tel=None,
            opening_hours=None,
            parking=parking,
            websites=(),
            facilities=(),
            coordinate=coordinate,
        )


def _parse_heading(heading: str) -> tuple[str, Direction | None, str | None]:
    """``h3.heading``の複合表記「名称（上り|下り：方面）」を解析する。

    複合表記(3要素: 名称・方向・方面)に一致する場合はローカル正規表現で
    方面まで含めて解析する。一致しない場合は、方面を伴わない単純な2要素
    表記「名称（上り）」/「名称（下り）」(コロン・方面なし)である可能性が
    あるため、共通ヘルパ(``normalize_direction``/``strip_direction_notation``)
    へフォールバックする。共通ヘルパも方向を認識できない場合は、方向表記を
    含まない上下集約施設とみなし、``strip_direction_notation``が返す(通常は
    見出しをそのまま整形しただけの)名称をそのまま用いる。
    """
    match = _HEADING_COMPOUND_PATTERN.match(heading)
    if match is None:
        direction = normalize_direction(heading)
        name = strip_direction_notation(heading)
        return name, direction, None

    name = match.group("name").strip()
    direction_text = match.group("direction")
    direction = Direction.UP if direction_text == "上り" else Direction.DOWN
    area_direction = match.group("area_direction").strip() or None
    return name, direction, area_direction


def _parse_road_name(raw: str) -> str | None:
    """``.sapa_summary``最初の``<p>``テキストから路線コードを除いた路線名を返す。

    実測の生テキストは「E1\\n        東名高速道路」のように路線コード
    (「E1」等)と路線名が改行・空白で連結されている(``get_text()``がタグ間の
    空白のみを残して結合するため)。空白区切りでトークン化し、先頭から
    ``^[A-Z0-9]{1,5}$``に一致する短い英数字トークン(路線コード)を除去した
    残りを路線名とする。呼び出し側は``road_paragraphs``が空でないことを
    確認してから呼び出す(空リストなら``None``を渡さず呼び出し自体をしない)。
    """
    tokens = raw.split()
    while tokens and _ROUTE_CODE_TOKEN_PATTERN.match(tokens[0]):
        tokens.pop(0)
    road_name = " ".join(tokens).strip()
    return road_name or None


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
    """駐車場pタグを大型・普通車の台数へ分解する(小型→standardへの写像)。

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


def _parse_coordinate(page: HtmlPage) -> Coordinate | None:
    """GoogleマップリンクのURLから``@{lat},{lon},``部分を抽出し``Coordinate``へ変換する。

    リンク自体が存在しない、またはURLがこの形式に一致しない場合は``None``を
    返す(この施設は座標補完(4.2)へフォールバックする。呼び出し側の責務)。
    """
    href = page.find_attr(_MAP_LINK_SELECTOR, "href")
    if href is None:
        return None

    match = _MAP_COORDINATE_PATTERN.search(href)
    if match is None:
        return None

    latitude = float(match.group(1))
    longitude = float(match.group(2))
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None

    return Coordinate(longitude=longitude, latitude=latitude)
