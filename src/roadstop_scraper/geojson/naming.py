"""出力ファイル名の生成・解析・検証を一元化するモジュール。

``(都道府県番号2桁)_(都道府県名ローマ字)_(michinoeki|sapa).geojson`` という
命名規則(4.1)の唯一の定義箇所であり、生成と解析の往復一致を保証する。
番号範囲外・ローマ字名と対応表の不整合・未知の施設種別・パターン不一致は
:class:`InvalidGeoJsonFilenameError` で拒否する。
"""

from __future__ import annotations

import re
from pathlib import Path

from roadstop_scraper.geojson.models import FacilityKind
from roadstop_scraper.geojson.prefectures import (
    Prefecture,
    UnknownPrefectureError,
    find_prefecture,
)

__all__ = [
    "DEFAULT_OUTPUT_DIR",
    "InvalidGeoJsonFilenameError",
    "build_geojson_filename",
    "parse_geojson_filename",
]


DEFAULT_OUTPUT_DIR = Path("geo-json")
"""出力先ディレクトリの既定値(4.5)。"""

# ファイル名パターンの唯一の定義箇所。番号はゼロ埋め2桁の01〜47、ローマ字名は
# 小文字英字のみ、施設種別はmichinoeki/sapaの2値に限定する(4.1〜4.4)。
_FILENAME_PATTERN = re.compile(
    r"^(0[1-9]|[1-3][0-9]|4[0-7])_([a-z]+)_(michinoeki|sapa)\.geojson$"
)


class InvalidGeoJsonFilenameError(ValueError):
    """命名規則に適合しないファイル名が指定された場合に送出される。"""


def build_geojson_filename(prefecture: Prefecture, kind: FacilityKind) -> str:
    """命名規則に適合するファイル名を生成する。

    例: ``build_geojson_filename(find_prefecture("01"), FacilityKind.MICHINOEKI)``
    は ``"01_hokkaido_michinoeki.geojson"`` を返す。
    """
    return f"{prefecture.code}_{prefecture.romaji}_{kind.value}.geojson"


def parse_geojson_filename(filename: str) -> tuple[Prefecture, FacilityKind]:
    """ファイル名を解析して構成要素へ復元する。

    ``parse_geojson_filename(build_geojson_filename(p, k)) == (p, k)`` の往復一致を
    保証する。パターン不一致・番号範囲外・未知の施設種別・番号とローマ字名の
    不整合は :class:`InvalidGeoJsonFilenameError` を送出する。入力はパス区切りを
    含まないファイル名単体であること。
    """
    match = _FILENAME_PATTERN.fullmatch(filename)
    if match is None:
        raise InvalidGeoJsonFilenameError(
            f"命名規則に適合しないファイル名です: {filename!r}"
            "(期待する形式: '(01〜47)_(ローマ字)_(michinoeki|sapa).geojson')"
        )

    code, romaji, kind_value = match.group(1), match.group(2), match.group(3)

    # パターンで番号の桁・範囲は担保済みだが、対応表実在の唯一の正はprefecturesに置く
    try:
        prefecture = find_prefecture(code)
    except UnknownPrefectureError as error:
        raise InvalidGeoJsonFilenameError(str(error)) from error

    # 番号とローマ字名が対応表と整合することを確認する(往復一致の要)
    if romaji != prefecture.romaji:
        raise InvalidGeoJsonFilenameError(
            f"都道府県番号とローマ字名が対応表と一致しません: {filename!r}"
            f"(番号 {code!r} は {prefecture.romaji!r} に対応)"
        )

    # kind_valueはパターンでmichinoeki|sapaに限定済みのため必ず変換できる
    return prefecture, FacilityKind(kind_value)
