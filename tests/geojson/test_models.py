import dataclasses
import json
from datetime import UTC, datetime

import pytest

from roadstop_scraper.geojson.models import (
    Coordinate,
    Direction,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    FacilityStatus,
    Parking,
    to_feature_collection_dict,
)


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
    )


def test_施設種別の検証_FacilityKindが_定義済みだった場合_道の駅とSAPAの2値である():
    # 施設種別がJSON出力値と一致する2値列挙であることを確認する(2.3)
    assert FacilityKind.MICHINOEKI == "michinoeki"
    assert FacilityKind.SAPA == "sapa"
    assert len(FacilityKind) == 2


def test_上下区分の検証_Directionが_定義済みだった場合_日本語の上りと下りの2値である():
    # 上り/下り区分が正規化後の日本語2値列挙であることを確認する(2.7)
    assert Direction.UP == "上り"
    assert Direction.DOWN == "下り"
    assert len(Direction) == 2


def test_削除状態の検証_FacilityStatusが_定義済みだった場合_activeとdeletedの2値である():
    # 削除状態がJSON出力値と一致する2値列挙であることを確認する(8.2, 8.3)
    assert FacilityStatus.ACTIVE == "active"
    assert FacilityStatus.DELETED == "deleted"
    assert len(FacilityStatus) == 2


def test_座標型の検証_Coordinateが_経度と緯度を指定された場合_WGS84の値を保持する():
    # 経度・緯度がそれぞれのフィールドに保持されることを確認する(3.1)
    coordinate = Coordinate(longitude=140.11, latitude=36.08)

    assert coordinate.longitude == 140.11
    assert coordinate.latitude == 36.08


def test_駐車場型の検証_Parkingが_省略構築された場合_全内訳がNoneである():
    # 台数内訳(大型・普通車・身障者用)がすべて任意であることを確認する(2.5)
    parking = Parking()

    assert (parking.large, parking.standard, parking.disabled) == (None, None, None)


def test_properties型の検証_必須項目のみで構築された場合_任意項目は既定値になる():
    # 必須4項目のみで構築でき、任意項目がNoneまたは空タプルに初期化されることを
    # 確認する(2.1, 2.4, 2.9)
    properties = FacilityProperties(
        name="道の駅テスト",
        kind=FacilityKind.MICHINOEKI,
        pref_code="01",
        pref_name="北海道",
    )

    assert properties.name == "道の駅テスト"
    assert properties.kind is FacilityKind.MICHINOEKI
    assert properties.pref_code == "01"
    assert properties.pref_name == "北海道"
    assert properties.address is None
    assert properties.postal_code is None
    assert properties.tel is None
    assert properties.opening_hours is None
    assert properties.parking is None
    assert properties.websites == ()
    assert properties.source_url is None
    assert properties.facilities == ()
    assert properties.road_name is None
    assert properties.direction is None
    assert properties.area_direction is None
    assert properties.mapcode is None
    assert properties.status is FacilityStatus.ACTIVE
    assert properties.last_confirmed_at is None


def test_properties型の検証_全項目を指定して構築された場合_指定値を保持する():
    # 共通任意項目・SA/PA固有項目・道の駅固有項目が同一の型に同居し、
    # 指定した値がそのまま保持されることを確認する(2.2, 2.5-2.8, 1.4)
    properties = _build_full_properties()

    assert properties.parking == Parking(large=10, standard=100, disabled=2)
    assert properties.websites == ("https://example.com/", "https://example.org/")
    assert properties.facilities == ("トイレ", "レストラン")
    assert properties.road_name == "常磐自動車道"
    assert properties.direction is Direction.UP
    assert properties.area_direction == "東京方面"
    assert properties.mapcode == "123 456 789*00"


def test_Feature型の検証_座標とpropertiesを指定された場合_施設1件として保持する():
    # 施設1件が座標とpropertiesの組で表現されることを確認する(1.4)
    feature = FacilityFeature(
        coordinate=Coordinate(longitude=140.11, latitude=36.08),
        properties=_build_full_properties(),
    )

    assert feature.coordinate.longitude == 140.11
    assert feature.properties.name == "テスト施設"


def _build_feature(properties: FacilityProperties) -> FacilityFeature:
    # 座標を固定した施設1件を組み立てる(propertiesのみ差し替えて検証する)
    return FacilityFeature(
        coordinate=Coordinate(longitude=140.11, latitude=36.08),
        properties=properties,
    )


def test_変換の検証_Feature列が_渡された場合_RFC7946のFeatureCollection構造になる():
    # ルートがFeatureCollection・各要素がPoint型Featureになることを確認する(1.1-1.3)
    result = to_feature_collection_dict([_build_feature(_build_full_properties())])

    assert result["type"] == "FeatureCollection"
    assert isinstance(result["features"], list)
    feature = result["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"


def test_変換の検証_座標が_出力された場合_経度緯度の順で並ぶ():
    # coordinatesが[経度, 緯度]の順序であることを確認する(3.2)
    result = to_feature_collection_dict([_build_feature(_build_full_properties())])

    coordinates = result["features"][0]["geometry"]["coordinates"]
    assert coordinates == [140.11, 36.08]


def test_変換の検証_FeatureCollectionが_出力された場合_crsメンバを含まない():
    # WGS84が規定値のためcrsメンバを出力しないことを確認する(3.1・RFC 7946)
    result = to_feature_collection_dict([_build_feature(_build_full_properties())])

    assert "crs" not in result
    assert "crs" not in result["features"][0]


def test_変換の検証_全項目つき施設が_出力された場合_データ契約のキーと型に一致する():
    # design.mdのデータ契約表(キー名・型・列挙値)どおりに出力されることを確認する
    result = to_feature_collection_dict([_build_feature(_build_full_properties())])

    props = result["features"][0]["properties"]
    assert props["name"] == "テスト施設"
    assert props["kind"] == "sapa"
    assert props["pref_code"] == "08"
    assert props["pref_name"] == "茨城県"
    assert props["address"] == "茨城県つくば市1-2-3"
    assert props["postal_code"] == "305-0001"
    assert props["tel"] == "029-000-0000"
    assert props["opening_hours"] == "24時間"
    assert props["parking"] == {"large": 10, "standard": 100, "disabled": 2}
    assert props["websites"] == ["https://example.com/", "https://example.org/"]
    assert props["source_url"] == "https://example.net/source"
    assert props["facilities"] == ["トイレ", "レストラン"]
    assert props["road_name"] == "常磐自動車道"
    assert props["direction"] == "上り"
    assert props["area_direction"] == "東京方面"
    assert props["mapcode"] == "123 456 789*00"


def test_変換の検証_列挙項目が_生文字列で渡された場合_enum指定時と同一のJSON値を出力する():
    # validationは正規化後の生文字列(enumではなくstr)も適合と扱うため、
    # シリアライズも同じ契約で受理し、enum指定時と同一の出力になることを確認する
    properties = FacilityProperties(
        name="テスト施設",
        kind="sapa",  # type: ignore[arg-type]
        pref_code="08",
        pref_name="茨城県",
        direction="上り",  # type: ignore[arg-type]
    )

    props = to_feature_collection_dict([_build_feature(properties)])["features"][0]["properties"]

    assert props["kind"] == "sapa"
    assert props["direction"] == "上り"


def test_変換の検証_必須項目のみの施設が_出力された場合_任意項目のキーを省略する():
    # 値が無い任意項目はキーごと省略されることを確認する(2.9)
    properties = FacilityProperties(
        name="道の駅テスト",
        kind=FacilityKind.MICHINOEKI,
        pref_code="01",
        pref_name="北海道",
    )

    props = to_feature_collection_dict([_build_feature(properties)])["features"][0]["properties"]

    assert props == {
        "name": "道の駅テスト",
        "kind": "michinoeki",
        "pref_code": "01",
        "pref_name": "北海道",
    }


def test_変換の検証_削除状態が_既定値だった場合_statusキーを省略する():
    # status既定(ACTIVE)の施設ではJSON出力にstatusキーが含まれないことを確認する
    # (Data Contracts & Integration: ACTIVEの場合はキー省略)
    properties = FacilityProperties(
        name="道の駅テスト",
        kind=FacilityKind.MICHINOEKI,
        pref_code="01",
        pref_name="北海道",
    )

    props = to_feature_collection_dict([_build_feature(properties)])["features"][0]["properties"]

    assert "status" not in props
    assert "last_confirmed_at" not in props


def test_変換の検証_削除状態が_deletedだった場合_statusキーと最終確認日時を出力する():
    # DELETEDの施設ではJSON出力に"status": "deleted"とlast_confirmed_atが
    # ISO 8601文字列で含まれることを確認する(8.2)
    last_confirmed_at = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    properties = FacilityProperties(
        name="道の駅テスト",
        kind=FacilityKind.MICHINOEKI,
        pref_code="01",
        pref_name="北海道",
        status=FacilityStatus.DELETED,
        last_confirmed_at=last_confirmed_at,
    )

    props = to_feature_collection_dict([_build_feature(properties)])["features"][0]["properties"]

    assert props["status"] == "deleted"
    assert props["last_confirmed_at"] == last_confirmed_at.isoformat()


def test_変換の検証_駐車場が_一部内訳のみだった場合_None内訳のキーを省略する():
    # parkingオブジェクト内でも値の無い内訳キーは省略されることを確認する(2.9)
    properties = FacilityProperties(
        name="道の駅テスト",
        kind=FacilityKind.MICHINOEKI,
        pref_code="01",
        pref_name="北海道",
        parking=Parking(large=5),
    )

    props = to_feature_collection_dict([_build_feature(properties)])["features"][0]["properties"]

    assert props["parking"] == {"large": 5}


def test_変換の検証_空のタグ列が_渡された場合_該当キーを省略する():
    # 空タプルのwebsites/facilitiesは値なしとしてキーごと省略されることを確認する(2.9)
    properties = FacilityProperties(
        name="道の駅テスト",
        kind=FacilityKind.MICHINOEKI,
        pref_code="01",
        pref_name="北海道",
        websites=(),
        facilities=(),
    )

    props = to_feature_collection_dict([_build_feature(properties)])["features"][0]["properties"]

    assert "websites" not in props
    assert "facilities" not in props


def test_変換の検証_Feature列が_空だった場合_空のfeatures配列を返す():
    # 施設0件でも構造上有効なFeatureCollectionになることを確認する(1.1)
    result = to_feature_collection_dict([])

    assert result == {"type": "FeatureCollection", "features": []}


def test_変換の検証_複数施設が_渡された場合_件数分のFeatureを出力する():
    # Feature列の各要素が1つのFeatureへ対応することを確認する(1.2)
    features = [
        _build_feature(
            FacilityProperties(
                name=f"施設{i}",
                kind=FacilityKind.MICHINOEKI,
                pref_code="01",
                pref_name="北海道",
            )
        )
        for i in range(3)
    ]

    result = to_feature_collection_dict(features)

    assert len(result["features"]) == 3


def test_変換の検証_変換結果が_JSON往復された場合_構造が保たれる():
    # JSONとして書き出して再読込しても同一の構造になることを確認する(5.6の再読込観点)
    result = to_feature_collection_dict([_build_feature(_build_full_properties())])

    reloaded = json.loads(json.dumps(result, ensure_ascii=False))

    assert reloaded == result


@pytest.mark.parametrize(
    "instance, field_name, value",
    [
        (Coordinate(longitude=140.0, latitude=36.0), "longitude", 0.0),
        (Parking(large=1), "large", 99),
        (
            FacilityProperties(
                name="道の駅テスト",
                kind=FacilityKind.MICHINOEKI,
                pref_code="01",
                pref_name="北海道",
            ),
            "name",
            "書き換え",
        ),
        (
            FacilityFeature(
                coordinate=Coordinate(longitude=140.0, latitude=36.0),
                properties=FacilityProperties(
                    name="道の駅テスト",
                    kind=FacilityKind.MICHINOEKI,
                    pref_code="01",
                    pref_name="北海道",
                ),
            ),
            "coordinate",
            None,
        ),
    ],
)
def test_不変性の検証_各データ型が_構築済みだった場合_属性の変更が禁止されている(instance, field_name, value):
    # 構築後の書き換えがFrozenInstanceErrorで拒否されることを確認する
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, field_name, value)
