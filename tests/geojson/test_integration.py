"""公開APIの単一importパス確認と、出力→index登録→整合性検証の統合テスト。

タスク4.2の観測可能な完了条件を検証する:

- 型・変換・検証・出力の公開APIが ``roadstop_scraper.geojson`` の単一import
  パスから利用できること
- 出力→index登録→整合性検証の往復が一時ディレクトリ上の実ファイルで成功すること
  (6.1–6.3)
"""

import json

import roadstop_scraper.geojson as geojson
from roadstop_scraper.common.index_store import (
    load_index,
    save_index,
    upsert_entry,
)
from roadstop_scraper.geojson import (
    Coordinate,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    build_geojson_filename,
    find_prefecture,
    validate_features,
    validate_index_consistency,
    write_geojson,
)


def _valid_feature() -> FacilityFeature:
    return FacilityFeature(
        coordinate=Coordinate(longitude=141.0, latitude=43.0),
        properties=FacilityProperties(
            name="道の駅テスト",
            kind=FacilityKind.MICHINOEKI,
            pref_code="01",
            pref_name="北海道",
        ),
    )


def test_公開APIの検証_geojsonパッケージが_出力APIを参照された場合_単一importパスから利用できる():
    # 型・変換・検証・出力の公開APIが個別モジュールを知らずとも参照できる。
    # 特にwriterの出力API(write_geojson・GeoJsonValidationError)が再公開される。
    for symbol in (
        "Coordinate",
        "FacilityFeature",
        "FacilityKind",
        "FacilityProperties",
        "to_feature_collection_dict",
        "build_geojson_filename",
        "validate_features",
        "validate_index_consistency",
        "write_geojson",
        "GeoJsonValidationError",
    ):
        assert symbol in geojson.__all__
        assert hasattr(geojson, symbol)


def test_index連携の検証_出力からindex登録までが_適合データだった場合_整合性検証を通過する(
    tmp_path,
):
    # 出力→index登録→整合性検証の往復を実ファイルで確認する(6.1–6.3)。
    output_dir = tmp_path / "geo-json"
    prefecture = find_prefecture("01")
    filename = build_geojson_filename(prefecture, FacilityKind.MICHINOEKI)

    # 1. 検証ゲート付きライタで実ファイルを出力する
    output_path = write_geojson([_valid_feature()], filename, output_dir=output_dir)
    assert output_path.exists()

    # 2. 出力したファイル名を既存のindex.json管理機能で登録・永続化する
    index_path = output_dir / "index.json"
    index = upsert_entry(
        load_index(index_path),
        path=filename,
        updated_at=_now(),
    )
    save_index(index, index_path)

    # 3. 永続化したindex.jsonを読み直しても整合性検証を通過する
    reloaded = load_index(index_path)
    assert validate_index_consistency(reloaded) == []

    # 出力したGeoJSON自体も適合(空の違反リスト)であることを併せて確認する
    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["type"] == "FeatureCollection"
    assert validate_features([_valid_feature()]) == []


def test_index連携の検証_命名規則違反のpathが_index登録された場合_整合性検証で違反を報告する(
    tmp_path,
):
    # 命名規則に反するpathをindexへ登録した場合、整合性検証が違反を検出する(6.4)。
    index_path = tmp_path / "geo-json" / "index.json"
    index = upsert_entry(load_index(index_path), path="invalid.geojson", updated_at=_now())
    save_index(index, index_path)

    reloaded = load_index(index_path)
    issues = validate_index_consistency(reloaded)
    assert len(issues) == 1
    assert issues[0].location == "index.files[0].path"


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
