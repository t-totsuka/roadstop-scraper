"""実行対象範囲(全国・地方8区分・都道府県)の解決。

運用者が指定する`ScopeSpec`(地方区分または都道府県コード)を、処理対象の
`Prefecture`列へ解決する。参照データ(`REGIONS`)のみに依存する純粋関数で
構成し、HTTPリクエストは一切発生しない。

05-michinoeki-scraping・06-sapa-scraping間で共有される実行時関心の共有層
(`pipeline/`)に属し、site固有パッケージには依存しない。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from roadstop_scraper.geojson import (
    PREFECTURES,
    Prefecture,
    UnknownPrefectureError,
    find_prefecture,
)

__all__ = ["REGIONS", "InvalidScopeError", "ScopeSpec", "resolve_scope"]


class InvalidScopeError(ValueError):
    """regionとprefecture_codeが同時指定された場合、または値が対応表に存在しない場合に送出される。"""


@dataclass(frozen=True)
class ScopeSpec:
    """運用者が指定する実行対象範囲。"""

    region: str | None = None
    """8地方区分キー(例: "hokkaido")。未指定はNone。"""

    prefecture_code: str | None = None
    """公式都道府県コード("01"〜"47")。未指定はNone。"""


REGIONS: Mapping[str, tuple[str, ...]] = {
    "hokkaido": ("01",),
    "tohoku": ("02", "03", "04", "05", "06", "07"),
    "kanto": ("08", "09", "10", "11", "12", "13", "14"),
    "chubu": ("15", "16", "17", "18", "19", "20", "21", "22", "23"),
    "kinki": ("24", "25", "26", "27", "28", "29", "30"),
    "chugoku": ("31", "32", "33", "34", "35"),
    "shikoku": ("36", "37", "38", "39"),
    "kyushu_okinawa": ("40", "41", "42", "43", "44", "45", "46", "47"),
}
"""地方区分名 -> 所属する都道府県コード列(公式コード)。8区分・47件で過不足なし。"""


def resolve_scope(spec: ScopeSpec) -> tuple[Prefecture, ...]:
    """ScopeSpecから処理対象のPrefecture列を解決する。両方省略時は全47都道府県。"""
    if spec.region is not None and spec.prefecture_code is not None:
        raise InvalidScopeError(
            "regionとprefecture_codeは同時に指定できません: "
            f"region={spec.region!r}, prefecture_code={spec.prefecture_code!r}"
        )

    if spec.region is not None:
        try:
            codes = REGIONS[spec.region]
        except KeyError:
            raise InvalidScopeError(f"未知の地方区分です: {spec.region!r}(有効な値は {sorted(REGIONS)})") from None
        return tuple(find_prefecture(code) for code in codes)

    if spec.prefecture_code is not None:
        try:
            return (find_prefecture(spec.prefecture_code),)
        except UnknownPrefectureError as error:
            raise InvalidScopeError(str(error)) from error

    return PREFECTURES
