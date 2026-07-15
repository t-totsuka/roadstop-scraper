"""GeoJSON出力スキーマ(03-geojson-schema)の公開API。

利用側はこのモジュールだけをimportすればよい。個別モジュール
(``prefectures`` 等)への直接依存は不要。
"""

from roadstop_scraper.geojson.models import (
    Coordinate,
    Direction,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    FacilityStatus,
    Parking,
    from_feature_collection_dict,
    to_feature_collection_dict,
)
from roadstop_scraper.geojson.naming import (
    DEFAULT_OUTPUT_DIR,
    InvalidGeoJsonFilenameError,
    build_geojson_filename,
    parse_geojson_filename,
)
from roadstop_scraper.geojson.prefectures import (
    PREFECTURES,
    Prefecture,
    UnknownPrefectureError,
    find_prefecture,
)
from roadstop_scraper.geojson.reader import read_geojson
from roadstop_scraper.geojson.validation import (
    ValidationIssue,
    validate_features,
    validate_filename,
    validate_index_consistency,
)
from roadstop_scraper.geojson.writer import (
    GeoJsonValidationError,
    write_geojson,
)

__all__ = [
    "DEFAULT_OUTPUT_DIR",
    "PREFECTURES",
    "Coordinate",
    "Direction",
    "FacilityFeature",
    "FacilityKind",
    "FacilityProperties",
    "FacilityStatus",
    "GeoJsonValidationError",
    "InvalidGeoJsonFilenameError",
    "Parking",
    "Prefecture",
    "UnknownPrefectureError",
    "ValidationIssue",
    "build_geojson_filename",
    "find_prefecture",
    "from_feature_collection_dict",
    "parse_geojson_filename",
    "read_geojson",
    "to_feature_collection_dict",
    "validate_features",
    "validate_filename",
    "validate_index_consistency",
    "write_geojson",
]
