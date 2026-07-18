from datetime import UTC, datetime

from roadstop_scraper.geojson.models import (
    Coordinate,
    Direction,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    FacilityStatus,
    Parking,
)
from roadstop_scraper.geojson.reader import read_geojson
from roadstop_scraper.geojson.writer import write_geojson


def _build_full_properties() -> FacilityProperties:
    # 全項目(必須+共通任意+SA/PA固有+道の駅固有)を指定したpropertiesを構築する
    return FacilityProperties(
        name="テスト施設",
        kind=FacilityKind.SAPA,
        pref_code="08",
        pref_name="茨城県",
        address="茨城県つくば市1-2-3",
        postal_code="305-0001",
        tel="029-000-0000",
        opening_hours="24時間",
        parking=Parking(large=10, standard=100, disabled=2),
        websites=("https://example.com/", "https://example.org/"),
        source_url="https://example.net/source",
        facilities=("トイレ", "レストラン"),
        road_name="常磐自動車道",
        direction=Direction.UP,
        area_direction="東京方面",
        mapcode="123 456 789*00",
        status=FacilityStatus.DELETED,
        last_confirmed_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
    )


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


def test_読み戻しの検証_read_geojsonが_write_geojson済みファイルだった場合_書き込み前のFeature列と一致する(
    tmp_path,
):
    # 削除状態・最終確認日時を含む全項目を、書き込み前のFacilityFeature列と一致する形で
    # 復元できることを確認する(8.1, 8.2, 8.4)
    output_dir = tmp_path / "geo-json"
    features = [
        FacilityFeature(
            coordinate=Coordinate(longitude=140.11, latitude=36.08),
            properties=_build_full_properties(),
        ),
        FacilityFeature(
            coordinate=Coordinate(longitude=141.0, latitude=43.0),
            properties=_valid_properties(),
        ),
    ]
    output_path = write_geojson(features, "01_hokkaido_michinoeki.geojson", output_dir=output_dir)

    restored = read_geojson(output_path)

    assert restored == features


def test_読み戻しの検証_read_geojsonが_存在しないパスだった場合_空リストを返す(tmp_path):
    # 初回実行・前回ファイル未存在のケースでは、load_indexが空のIndexDataを返す
    # 既存パターンと同じ方針で空リストを返すことを確認する
    missing_path = tmp_path / "geo-json" / "01_hokkaido_michinoeki.geojson"

    restored = read_geojson(missing_path)

    assert restored == []
