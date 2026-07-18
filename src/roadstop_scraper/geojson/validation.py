"""Feature列のスキーマ違反を網羅的に収集して報告するモジュール。

検証は違反を発見しても打ち切らず、全Feature・全項目を走査して
:class:`ValidationIssue` のリストを返す(5.2の網羅的報告)。例外を投げるか
どうかは呼び出し側(writer)が決め、本モジュールは報告のみを担う。副作用は
持たず、入力を変更しない。

本モジュールが検証するルール:

- 必須文字列の非空(``name`` ・ ``pref_name``)
- ``kind`` ・ ``direction`` の列挙値
- ``pref_code`` の実在と ``pref_name`` との整合
- 座標の値域(緯度±90・経度±180)。``NaN`` / ``inf`` は値域違反として扱う
- 出力ファイル名の命名規則適合(5.4)
- ``index.json`` の各エントリの ``path`` の命名規則適合(6.1, 6.2, 6.4)

``updated_at`` のISO 8601形式(6.3)は ``common.index_store`` の ``datetime``
型が既に保証しているため、本モジュールでは ``path`` の検証のみを追加する。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from roadstop_scraper.common.index_store import IndexData
from roadstop_scraper.geojson.models import (
    Coordinate,
    Direction,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    FacilityStatus,
)
from roadstop_scraper.geojson.naming import (
    InvalidGeoJsonFilenameError,
    parse_geojson_filename,
)
from roadstop_scraper.geojson.prefectures import (
    UnknownPrefectureError,
    find_prefecture,
)

__all__ = [
    "ValidationIssue",
    "validate_features",
    "validate_filename",
    "validate_index_consistency",
]

# 緯度・経度の許容値域(3.3)。境界値ちょうどは適合として扱う。
_LATITUDE_RANGE = (-90.0, 90.0)
_LONGITUDE_RANGE = (-180.0, 180.0)


@dataclass(frozen=True)
class ValidationIssue:
    """検証で見つかった違反1件。

    :attr:`location` は違反箇所(例: ``"features[3].properties.name"``)、
    :attr:`message` は違反理由(日本語)。戻り値が空リストであることと
    「スキーマ適合」が同値になるよう、適合時はインスタンスを生成しない。
    """

    location: str
    """違反箇所を指すパス。"""

    message: str
    """違反理由(日本語)。"""


def _is_valid_enum_value(value: object, enum_cls: type[Enum]) -> bool:
    # 既にenumインスタンスなら適合。生の文字列で渡された場合も値として引けるなら
    # 適合とみなす(05/06が正規化後の素の値を渡す経路を許容する)。
    if isinstance(value, enum_cls):
        return True
    try:
        enum_cls(value)
    except ValueError:
        return False
    return True


def _is_non_empty_string(value: object) -> bool:
    # 空文字・空白のみは「非空」を満たさない。
    return isinstance(value, str) and value.strip() != ""


def _check_required_strings(properties: FacilityProperties, prefix: str, issues: list[ValidationIssue]) -> None:
    # 必須文字列(name・pref_name)の非空を検証する。
    if not _is_non_empty_string(properties.name):
        issues.append(ValidationIssue(f"{prefix}.name", "施設名称は必須で、空にできません"))
    if not _is_non_empty_string(properties.pref_name):
        issues.append(ValidationIssue(f"{prefix}.pref_name", "都道府県名は必須で、空にできません"))


def _check_enums(properties: FacilityProperties, prefix: str, issues: list[ValidationIssue]) -> None:
    # 施設種別(必須)と上り/下り区分(任意)の列挙値を検証する。
    if not _is_valid_enum_value(properties.kind, FacilityKind):
        valid = ", ".join(member.value for member in FacilityKind)
        issues.append(
            ValidationIssue(
                f"{prefix}.kind",
                f"施設種別が列挙値ではありません: {properties.kind!r}(有効値: {valid})",
            )
        )
    if properties.direction is not None and not _is_valid_enum_value(properties.direction, Direction):
        valid = ", ".join(member.value for member in Direction)
        issues.append(
            ValidationIssue(
                f"{prefix}.direction",
                f"上り/下り区分が列挙値ではありません: {properties.direction!r}(有効値: {valid})",
            )
        )
    if not _is_valid_enum_value(properties.status, FacilityStatus):
        valid = ", ".join(member.value for member in FacilityStatus)
        issues.append(
            ValidationIssue(
                f"{prefix}.status",
                f"削除状態が列挙値ではありません: {properties.status!r}(有効値: {valid})",
            )
        )


def _check_prefecture(properties: FacilityProperties, prefix: str, issues: list[ValidationIssue]) -> None:
    # 都道府県番号の実在と、番号に対応する日本語名との整合を検証する。
    try:
        prefecture = find_prefecture(properties.pref_code)
    except UnknownPrefectureError:
        issues.append(
            ValidationIssue(
                f"{prefix}.pref_code",
                f"都道府県番号が対応表に存在しません: {properties.pref_code!r}",
            )
        )
        return
    # 番号が実在する場合のみ名称整合を検証する(番号違反の二重報告を避ける)。
    if properties.pref_name != prefecture.name_ja:
        issues.append(
            ValidationIssue(
                f"{prefix}.pref_name",
                f"都道府県名が番号 {properties.pref_code!r} と整合しません"
                f"(期待: {prefecture.name_ja!r}, 実際: {properties.pref_name!r})",
            )
        )


def _check_coordinate(coordinate: Coordinate, prefix: str, issues: list[ValidationIssue]) -> None:
    # 緯度・経度の値域を検証する。NaN/infはmath.isfiniteで弾き値域違反として扱う。
    checks = (
        ("longitude", coordinate.longitude, _LONGITUDE_RANGE),
        ("latitude", coordinate.latitude, _LATITUDE_RANGE),
    )
    for field, value, (low, high) in checks:
        if not (math.isfinite(value) and low <= value <= high):
            issues.append(
                ValidationIssue(
                    f"{prefix}.{field}",
                    f"座標が値域[{low}, {high}]の外か解釈できない値です: {value!r}",
                )
            )


def validate_features(features: Sequence[FacilityFeature]) -> list[ValidationIssue]:
    """Feature列のスキーマ適合性を検証し、違反を全件返す。

    必須文字列の非空・列挙値・都道府県の実在と整合・座標値域を全Feature・
    全項目にわたって走査する。最初の違反で打ち切らず、見つかった違反を
    :class:`ValidationIssue` のリストとして返す。適合時は空リスト。入力は
    変更しない。
    """
    issues: list[ValidationIssue] = []
    for index, feature in enumerate(features):
        properties_prefix = f"features[{index}].properties"
        coordinate_prefix = f"features[{index}].coordinate"
        _check_required_strings(feature.properties, properties_prefix, issues)
        _check_enums(feature.properties, properties_prefix, issues)
        _check_prefecture(feature.properties, properties_prefix, issues)
        _check_coordinate(feature.coordinate, coordinate_prefix, issues)
    return issues


def _check_filename(filename: str, location: str) -> ValidationIssue | None:
    # 命名規則の唯一の正であるnamingへ委譲する。パターン不一致・番号範囲外・
    # 未知の施設種別・番号とローマ字名の不整合はいずれも違反として扱う。
    try:
        parse_geojson_filename(filename)
    except InvalidGeoJsonFilenameError as error:
        return ValidationIssue(location, str(error))
    return None


def validate_filename(filename: str) -> list[ValidationIssue]:
    """ファイル名の命名規則適合性を検証する(5.4)。

    ``build_geojson_filename`` が生成する形式に適合すれば空リスト、そうでなければ
    ``location`` を ``"filename"`` とした違反1件を返す。出力ゲート(writer)が
    書き込み前検証に利用する。入力は変更しない。
    """
    issue = _check_filename(filename, "filename")
    return [issue] if issue is not None else []


def validate_index_consistency(index: IndexData) -> list[ValidationIssue]:
    """``index.json`` の各エントリの ``path`` が命名規則に適合するかを検証する(6.1, 6.2, 6.4)。

    ``path`` は ``geo-json/`` からの相対ファイル名(6.1)であり、これが命名規則
    (Requirement 4)に適合することを整合性ルールとして検証する。違反を発見しても
    打ち切らず、全エントリを走査して ``location`` を ``"index.files[i].path"`` とした
    違反を全件返す。適合時は空リスト。``updated_at`` のISO 8601形式(6.3)は
    ``index_store`` の ``datetime`` 型で保証済みのため、本関数では検証しない。
    入力は変更しない。
    """
    issues: list[ValidationIssue] = []
    for index_position, entry in enumerate(index.files):
        issue = _check_filename(entry.path, f"index.files[{index_position}].path")
        if issue is not None:
            issues.append(issue)
    return issues
