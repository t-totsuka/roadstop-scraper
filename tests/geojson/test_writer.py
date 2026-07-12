import json
import logging

import pytest

from roadstop_scraper.geojson.models import (
    Coordinate,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
)
from roadstop_scraper.geojson.validation import ValidationIssue
from roadstop_scraper.geojson.writer import GeoJsonValidationError, write_geojson


def _valid_properties(**overrides) -> FacilityProperties:
    # 必須4項目を満たす適合propertiesを作り、検証対象の項目だけを差し替える
    base = {
        "name": "道の駅テスト",
        "kind": FacilityKind.MICHINOEKI,
        "pref_code": "01",
        "pref_name": "北海道",
    }
    base.update(overrides)
    return FacilityProperties(**base)


def _valid_feature(coordinate: Coordinate | None = None, **overrides) -> FacilityFeature:
    return FacilityFeature(
        coordinate=coordinate or Coordinate(longitude=141.0, latitude=43.0),
        properties=_valid_properties(**overrides),
    )


def test_検証合格時の出力_write_geojsonが_適合データだった場合_geojsonファイルを生成する(
    tmp_path,
):
    # 適合データはgeo-json/配下(ここではtmp_path)にファイルとして生成される
    output_dir = tmp_path / "geo-json"
    features = [_valid_feature()]

    output_path = write_geojson(
        features, "01_hokkaido_michinoeki.geojson", output_dir=output_dir
    )

    assert output_path == output_dir / "01_hokkaido_michinoeki.geojson"
    assert output_path.exists()


def test_検証合格時の出力_write_geojsonが_列挙項目が生文字列だった場合_enum指定時と同様に出力する(
    tmp_path,
):
    # validationが適合と扱う生文字列(enumではなくstr)の経路でも、検証通過後の
    # シリアライズが失敗せず、enum指定時と同一のJSON値で出力されることを確認する
    output_dir = tmp_path / "geo-json"
    features = [
        _valid_feature(
            kind="sapa",
            pref_code="08",
            pref_name="茨城県",
            direction="上り",
        )
    ]

    output_path = write_geojson(
        features, "08_ibaraki_sapa.geojson", output_dir=output_dir
    )

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    props = loaded["features"][0]["properties"]
    assert props["kind"] == "sapa"
    assert props["direction"] == "上り"


def test_出力内容の検証_write_geojsonが_適合データだった場合_再読込した構造がスキーマに一致する(
    tmp_path,
):
    # 出力ファイルをJSONとして再読込するとFeatureCollection構造が復元できる
    output_dir = tmp_path / "geo-json"
    features = [
        _valid_feature(),
        _valid_feature(
            coordinate=Coordinate(longitude=127.6, latitude=26.2),
            name="道の駅おきなわ",
            pref_code="47",
            pref_name="沖縄県",
        ),
    ]

    output_path = write_geojson(
        features, "01_hokkaido_michinoeki.geojson", output_dir=output_dir
    )

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["type"] == "FeatureCollection"
    assert len(loaded["features"]) == 2
    first = loaded["features"][0]
    assert first["type"] == "Feature"
    assert first["geometry"] == {"type": "Point", "coordinates": [141.0, 43.0]}
    assert first["properties"]["name"] == "道の駅テスト"


def test_出力体裁の検証_write_geojsonが_適合データだった場合_日本語非エスケープ末尾改行で書き込む(
    tmp_path,
):
    # ensure_ascii=Falseで日本語がそのまま残り、末尾に改行が付く(index_storeと体裁を揃える)
    output_dir = tmp_path / "geo-json"

    output_path = write_geojson(
        [_valid_feature()], "01_hokkaido_michinoeki.geojson", output_dir=output_dir
    )

    text = output_path.read_text(encoding="utf-8")
    assert "道の駅テスト" in text
    assert text.endswith("\n")


def test_検証ゲートの検証_write_geojsonが_違反ありデータだった場合_例外を送出しファイルを作らない(
    tmp_path,
):
    # 必須項目欠落など違反があれば書き込まずにGeoJsonValidationErrorを送出する
    output_dir = tmp_path / "geo-json"
    features = [_valid_feature(name="")]

    with pytest.raises(GeoJsonValidationError):
        write_geojson(
            features, "01_hokkaido_michinoeki.geojson", output_dir=output_dir
        )

    assert not (output_dir / "01_hokkaido_michinoeki.geojson").exists()


def test_ファイル名検証の検証_write_geojsonが_命名規則違反のファイル名だった場合_例外を送出しファイルを作らない(
    tmp_path,
):
    # Feature自体は適合でも、ファイル名が命名規則違反なら書き込まない(5.4)
    output_dir = tmp_path / "geo-json"

    with pytest.raises(GeoJsonValidationError):
        write_geojson([_valid_feature()], "invalid.geojson", output_dir=output_dir)

    assert not (output_dir / "invalid.geojson").exists()
    # ディレクトリを作る前に検証で中断するため、出力先ディレクトリも作られない
    assert not output_dir.exists()


def test_全違反保持の検証_write_geojsonが_複数違反ありだった場合_例外が全違反を保持する(
    tmp_path,
):
    # 例外のissuesに全違反(Feature違反+ファイル名違反)が漏れなく保持される
    output_dir = tmp_path / "geo-json"
    features = [
        _valid_feature(name=""),
        _valid_feature(coordinate=Coordinate(longitude=200.0, latitude=43.0)),
    ]

    with pytest.raises(GeoJsonValidationError) as excinfo:
        write_geojson(features, "invalid.geojson", output_dir=output_dir)

    issues = excinfo.value.issues
    assert isinstance(issues, tuple)
    assert all(isinstance(issue, ValidationIssue) for issue in issues)
    locations = {issue.location for issue in issues}
    assert "filename" in locations
    assert "features[0].properties.name" in locations
    assert "features[1].coordinate.longitude" in locations


def test_冪等性の検証_write_geojsonが_同一入力で再実行された場合_同一内容で上書きする(
    tmp_path,
):
    # 同一入力の再実行は同一内容の上書きとなり冪等
    output_dir = tmp_path / "geo-json"
    features = [_valid_feature()]

    first = write_geojson(
        features, "01_hokkaido_michinoeki.geojson", output_dir=output_dir
    )
    first_text = first.read_text(encoding="utf-8")
    second = write_geojson(
        features, "01_hokkaido_michinoeki.geojson", output_dir=output_dir
    )

    assert second == first
    assert second.read_text(encoding="utf-8") == first_text


def test_ログ記録の検証_write_geojsonが_適合データだった場合_出力完了をINFOで記録する(
    tmp_path, caplog
):
    # 出力完了(INFO・パスと件数)を共通ロガーで記録する
    output_dir = tmp_path / "geo-json"

    with caplog.at_level(logging.INFO, logger="roadstop_scraper.geojson.writer"):
        write_geojson(
            [_valid_feature()], "01_hokkaido_michinoeki.geojson", output_dir=output_dir
        )

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1


def test_ログ記録の検証_write_geojsonが_違反ありだった場合_検証違反をWARNINGで記録する(
    tmp_path, caplog
):
    # 検証違反(WARNING・違反件数と要約)を共通ロガーで記録する
    output_dir = tmp_path / "geo-json"

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.geojson.writer"):
        with pytest.raises(GeoJsonValidationError):
            write_geojson(
                [_valid_feature(name="")],
                "01_hokkaido_michinoeki.geojson",
                output_dir=output_dir,
            )

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
