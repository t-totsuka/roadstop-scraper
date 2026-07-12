from pathlib import Path

import pytest

from roadstop_scraper.geojson.models import FacilityKind
from roadstop_scraper.geojson.naming import (
    DEFAULT_OUTPUT_DIR,
    InvalidGeoJsonFilenameError,
    build_geojson_filename,
    parse_geojson_filename,
)
from roadstop_scraper.geojson.prefectures import PREFECTURES, find_prefecture


def test_ファイル名生成の検証_build_geojson_filenameが_道の駅だった場合_命名規則に適合する():
    # design.mdの例(01_hokkaido_michinoeki.geojson)通りに生成されることを確認する
    hokkaido = find_prefecture("01")

    filename = build_geojson_filename(hokkaido, FacilityKind.MICHINOEKI)

    assert filename == "01_hokkaido_michinoeki.geojson"


def test_ファイル名生成の検証_build_geojson_filenameが_SAPAだった場合_命名規則に適合する():
    # 施設種別がsapaのときも規則に沿うことを確認する
    okinawa = find_prefecture("47")

    filename = build_geojson_filename(okinawa, FacilityKind.SAPA)

    assert filename == "47_okinawa_sapa.geojson"


@pytest.mark.parametrize("prefecture", PREFECTURES)
@pytest.mark.parametrize("kind", list(FacilityKind))
def test_往復一致の検証_47都道府県2種別の全組合せが_生成解析された場合_元の構成要素へ復元される(
    prefecture, kind,
):
    # parse(build(p, k)) == (p, k) の往復一致を47×2の全組合せで確認する
    filename = build_geojson_filename(prefecture, kind)

    parsed_prefecture, parsed_kind = parse_geojson_filename(filename)

    assert parsed_prefecture == prefecture
    assert parsed_kind == kind


def test_解析結果の検証_parse_geojson_filenameが_既知のファイル名だった場合_対応表のPrefectureを返す():
    # 解析結果が対応表と同一インスタンス相当の内容であることを確認する
    prefecture, kind = parse_geojson_filename("13_tokyo_sapa.geojson")

    assert (prefecture.code, prefecture.romaji, prefecture.name_ja) == (
        "13",
        "tokyo",
        "東京都",
    )
    assert kind is FacilityKind.SAPA


@pytest.mark.parametrize(
    "filename",
    [
        "00_hokkaido_michinoeki.geojson",  # 番号範囲外(下限未満)
        "48_okinawa_michinoeki.geojson",  # 番号範囲外(上限超過)
        "1_hokkaido_michinoeki.geojson",  # ゼロ埋めなし
        "01_HOKKAIDO_michinoeki.geojson",  # ローマ字が大文字
        "01_hokkaido_michi.geojson",  # 未知の施設種別
        "01_hokkaido_michinoeki.json",  # 拡張子不一致
        "01_hokkaido.geojson",  # 種別欠落(パターン不一致)
        "hokkaido_michinoeki.geojson",  # 番号欠落
        "01_hokkaido_michinoeki",  # 拡張子なし
        "",  # 空文字
    ],
)
def test_不正入力の検証_parse_geojson_filenameが_規則違反のファイル名だった場合_専用例外を送出する(
    filename,
):
    # 番号範囲外・大文字・未知種別・パターン不一致が拒否されることを確認する
    with pytest.raises(InvalidGeoJsonFilenameError):
        parse_geojson_filename(filename)


def test_整合性の検証_parse_geojson_filenameが_番号とローマ字が不整合だった場合_専用例外を送出する():
    # 番号(01=hokkaido)と対応表が一致しないローマ字名を拒否することを確認する
    with pytest.raises(InvalidGeoJsonFilenameError):
        parse_geojson_filename("01_tokyo_michinoeki.geojson")


def test_境界の検証_parse_geojson_filenameが_パス区切りを含む場合_専用例外を送出する():
    # 入力はファイル名単体であるべきで、ディレクトリ付きは拒否されることを確認する
    with pytest.raises(InvalidGeoJsonFilenameError):
        parse_geojson_filename("geo-json/01_hokkaido_michinoeki.geojson")


def test_例外型の検証_InvalidGeoJsonFilenameErrorが_送出された場合_ValueErrorとして捕捉できる():
    # 既存パッケージの例外パターン(ValueErrorサブクラス)に従うことを確認する
    with pytest.raises(ValueError):
        parse_geojson_filename("bad")


def test_既定値の検証_DEFAULT_OUTPUT_DIRが_定義済みだった場合_geo_jsonである():
    # 出力先ディレクトリの既定値がgeo-json/であることを確認する(4.5)
    assert DEFAULT_OUTPUT_DIR == Path("geo-json")
