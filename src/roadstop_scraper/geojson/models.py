"""施設1件を表す不変のデータ型定義。

道の駅・SA/PAで単一の :class:`FacilityProperties` 型を共有し、種別固有の項目は
任意フィールドとして同居させる。本モジュールは型としての構造保証(フィールドの
存在・型)までを担い、値の妥当性検証(空文字・値域・整合)は ``validation``
モジュールの責務とする。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "Coordinate",
    "Direction",
    "FacilityFeature",
    "FacilityKind",
    "FacilityProperties",
    "Parking",
    "to_feature_collection_dict",
]


class FacilityKind(StrEnum):
    """施設種別。値はJSON出力・ファイル名の構成要素と共通。"""

    MICHINOEKI = "michinoeki"
    SAPA = "sapa"


class Direction(StrEnum):
    """SA/PAの上り/下り区分。

    情報源の生の表記(「up」「上り線」等)からの正規化は05/06スクレイパの責務で、
    本specは正規化後の日本語2値のみを受理する。JSON出力値もこの日本語2値。
    """

    UP = "上り"
    DOWN = "下り"


@dataclass(frozen=True)
class Coordinate:
    """WGS84の座標。GeoJSON出力時は[経度, 緯度]の順序になる。"""

    longitude: float
    """経度(WGS84)。"""

    latitude: float
    """緯度(WGS84)。"""


@dataclass(frozen=True)
class Parking:
    """駐車場台数の内訳。情報源に無い区分はNoneのまま保持する。"""

    large: int | None = None
    """大型車の台数。"""

    standard: int | None = None
    """普通車の台数。"""

    disabled: int | None = None
    """身障者用の台数。"""


@dataclass(frozen=True)
class FacilityProperties:
    """GeoJSON Featureの ``properties`` に対応する施設情報。

    必須4項目以外はすべて任意で、値が無い項目はJSON出力時にキーごと省略される。
    JSONキーはフィールド名と同一のsnake_case英語キー(消費側アプリとの契約)。
    """

    name: str
    """必須: 施設名称。"""

    kind: FacilityKind
    """必須: 施設種別。"""

    pref_code: str
    """必須: 都道府県番号(ゼロ埋め2桁 "01"〜"47")。"""

    pref_name: str
    """必須: 都道府県名(日本語)。"""

    address: str | None = None
    """住所。"""

    postal_code: str | None = None
    """郵便番号。"""

    tel: str | None = None
    """電話番号。"""

    opening_hours: str | None = None
    """営業時間(自由記述)。"""

    parking: Parking | None = None
    """駐車場台数の内訳。"""

    websites: tuple[str, ...] = ()
    """施設ホームページURL列(道の駅は最大2件)。"""

    source_url: str | None = None
    """情報源URL。"""

    facilities: tuple[str, ...] = ()
    """施設設備・サービスのタグ列。"""

    road_name: str | None = None
    """SA/PA固有: 路線名。"""

    direction: Direction | None = None
    """SA/PA固有: 上り/下り区分。"""

    area_direction: str | None = None
    """SA/PA固有: 方面。"""

    mapcode: str | None = None
    """道の駅固有: マップコード。"""


@dataclass(frozen=True)
class FacilityFeature:
    """施設1件(集約)。座標とpropertiesを値オブジェクトとして内包する。"""

    coordinate: Coordinate
    """施設の位置。"""

    properties: FacilityProperties
    """施設の属性情報。"""


def _parking_to_dict(parking: Parking) -> dict[str, object]:
    # 内訳ごとにNoneでないものだけをキーとして残す(値の無い内訳は省略する)
    fields = (("large", parking.large), ("standard", parking.standard),
              ("disabled", parking.disabled))
    return {key: value for key, value in fields if value is not None}


def _properties_to_dict(properties: FacilityProperties) -> dict[str, object]:
    # 必須4項目は常に出力する。StrEnumは素の文字列値へ落としてから格納する。
    result: dict[str, object] = {
        "name": properties.name,
        "kind": properties.kind.value,
        "pref_code": properties.pref_code,
        "pref_name": properties.pref_name,
    }
    # 任意の文字列項目: Noneはキーごと省略する(2.9)
    optional_strings = (
        ("address", properties.address),
        ("postal_code", properties.postal_code),
        ("tel", properties.tel),
        ("opening_hours", properties.opening_hours),
        ("source_url", properties.source_url),
        ("road_name", properties.road_name),
        ("area_direction", properties.area_direction),
        ("mapcode", properties.mapcode),
    )
    for key, value in optional_strings:
        if value is not None:
            result[key] = value
    # 列挙・複合・配列項目: それぞれ値が無い状態(None・空タプル)ならキーを省略する
    if properties.parking is not None:
        result["parking"] = _parking_to_dict(properties.parking)
    if properties.direction is not None:
        result["direction"] = properties.direction.value
    if properties.websites:
        result["websites"] = list(properties.websites)
    if properties.facilities:
        result["facilities"] = list(properties.facilities)
    return result


def _feature_to_dict(feature: FacilityFeature) -> dict[str, object]:
    # geometryはPoint型・coordinatesは[経度, 緯度]順で出力する(3.2)
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [feature.coordinate.longitude, feature.coordinate.latitude],
        },
        "properties": _properties_to_dict(feature.properties),
    }


def to_feature_collection_dict(
    features: Sequence[FacilityFeature],
) -> dict[str, object]:
    """RFC 7946準拠のFeatureCollection辞書へ変換する。

    各施設は ``Point`` ジオメトリを持つ1つのFeatureとなり、座標は[経度, 緯度]順で
    出力する。値の無い任意項目はキーごと省略する(2.9)。WGS84が規定値のため
    ``crs`` メンバは出力しない。
    """
    return {
        "type": "FeatureCollection",
        "features": [_feature_to_dict(feature) for feature in features],
    }
