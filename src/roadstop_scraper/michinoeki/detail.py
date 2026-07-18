"""詳細ページからの付加情報抽出とプロパティへの変換(detail)。

対象の詳細ページ1回分のパース結果(``HtmlPage``)から、名称・所在地・電話番号・
駐車場台数・営業時間・施設ホームページ・マップコード・施設設備タグを抽出し、
道の駅向けの :class:`FacilityProperties` へ変換する。名称のみ位置固定
(``.info dl:nth-of-type(1) dd``)で必須取得し、それ以外の項目は
``.info dl dt``/``.info dl dd``をラベル文字列で辞書化してから参照することで、
要素数の変動(ホームページ2の有無等)に頑健にする
(research.md「詳細ページのDOM構造実測」参照)。
"""

from __future__ import annotations

import re

from roadstop_scraper.geojson import FacilityKind, FacilityProperties, Parking, Prefecture
from roadstop_scraper.scraping import HtmlPage

__all__ = ["extract_station_properties"]

_NAME_SELECTOR = ".info dl:nth-of-type(1) dd"
_LABEL_SELECTOR = ".info dl dt"
_VALUE_SELECTOR = ".info dl dd"
_FACILITY_SELECTOR = ".viewFacility li:not(.off) span"

_LABEL_ADDRESS = "所在地"
_LABEL_TEL = "TEL"
_LABEL_PARKING = "駐車場"
_LABEL_OPENING_HOURS = "営業時間"
_LABEL_WEBSITE = "ホームページ"
_LABEL_WEBSITE2 = "ホームページ2"
_LABEL_MAPCODE = "マップコード"

# 所在地dd(例: "068-2165 北海道三笠市岡山1056-1")を郵便番号と住所に分離する。
_POSTAL_CODE_PATTERN = re.compile(r"^(\d{3}-\d{4})\s*(.*)$")

# 駐車場dd(例: "大型：13台　普通車：202（身障者用2）台"、または「うち身障者用」表記)から
# 各区分の台数を独立に抽出する。前置詞の表記揺れをアンカーなしのsearchで吸収する。
_PARKING_LARGE_PATTERN = re.compile(r"大型：(\d+)台")
_PARKING_STANDARD_PATTERN = re.compile(r"普通車：(\d+)")
_PARKING_DISABLED_PATTERN = re.compile(r"身障者用(\d+)")


def extract_station_properties(
    page: HtmlPage,
    prefecture: Prefecture,
    coordinate_source_url: str,
) -> FacilityProperties:
    """詳細ページから道の駅のFacilityPropertiesを構築する。

    名称が取得できない場合はStructureChangedErrorを送出する。
    座標は含まない(呼び出し側がCoordinateと合成しFacilityFeatureを構築する)。
    """
    name = page.require_text(_NAME_SELECTOR)

    labels = page.find_texts(_LABEL_SELECTOR)
    values = page.find_texts(_VALUE_SELECTOR)
    # 位置に依存せずラベル文字列で参照する(要素数が変動しても頑健)。
    # dt/ddの件数が構造変化等で食い違っても例外にせず短い方に合わせて継続する
    # (全体の抽出を止めない、というこのモジュールの一貫した方針のため)。
    fields = dict(zip(labels, values, strict=False))

    postal_code, address = _split_address(fields.get(_LABEL_ADDRESS))
    facilities = tuple(page.find_texts(_FACILITY_SELECTOR))

    return FacilityProperties(
        name=name,
        kind=FacilityKind.MICHINOEKI,
        pref_code=prefecture.code,
        pref_name=prefecture.name_ja,
        address=address,
        postal_code=postal_code,
        tel=fields.get(_LABEL_TEL),
        opening_hours=fields.get(_LABEL_OPENING_HOURS),
        parking=_parse_parking(fields.get(_LABEL_PARKING)),
        websites=_collect_websites(fields),
        source_url=coordinate_source_url,
        facilities=facilities,
        mapcode=fields.get(_LABEL_MAPCODE),
    )


def _split_address(value: str | None) -> tuple[str | None, str | None]:
    """所在地ddを郵便番号と住所に分離する。

    キー自体が無い場合、またはパターンに一致しない場合は両方Noneを返す
    (「所在地の正規表現が一致しない場合は当該項目のみNoneとし、他の項目の
    抽出は継続する」design.md Implementation Notes参照)。
    """
    if value is None:
        return None, None
    match = _POSTAL_CODE_PATTERN.match(value)
    if match is None:
        return None, None
    return match.group(1), match.group(2)


def _parse_parking(value: str | None) -> Parking | None:
    """駐車場ddを大型・普通車・身障者用の台数へ分解する。

    キー自体が無ければNoneを返す。キーはあるが3パターンいずれも一致しない
    場合は全項目Noneの``Parking``を返す(値が取得できたこと自体は表す)。
    """
    if value is None:
        return None
    return Parking(
        large=_search_int(_PARKING_LARGE_PATTERN, value),
        standard=_search_int(_PARKING_STANDARD_PATTERN, value),
        disabled=_search_int(_PARKING_DISABLED_PATTERN, value),
    )


def _search_int(pattern: re.Pattern[str], value: str) -> int | None:
    """パターンに一致した数値を整数へ変換する。一致しない場合はNoneを返す。"""
    match = pattern.search(value)
    if match is None:
        return None
    return int(match.group(1))


def _collect_websites(fields: dict[str, str]) -> tuple[str, ...]:
    """ホームページ・ホームページ2のうち、値が存在しかつ空文字でないものだけを収集する。

    キー自体が無い場合・値が空文字の場合はいずれも除外する(Webサイトが1件
    のみの施設でも常に空のホームページ2 dt/ddが出力されるため)。
    """
    return tuple(value for value in (fields.get(_LABEL_WEBSITE), fields.get(_LABEL_WEBSITE2)) if value)
