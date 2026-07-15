import math
from datetime import UTC, datetime

import pytest

from roadstop_scraper.common.index_store import (
    IndexData,
    IndexEntry,
    load_index,
    save_index,
    upsert_entry,
)
from roadstop_scraper.geojson.models import (
    Coordinate,
    Direction,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    FacilityStatus,
)
from roadstop_scraper.geojson.validation import (
    ValidationIssue,
    validate_features,
    validate_filename,
    validate_index_consistency,
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


def _valid_feature(coordinate: Coordinate | None = None, **overrides) -> FacilityFeature:
    # 値域内の座標と適合propertiesを持つFeatureを作る
    return FacilityFeature(
        coordinate=coordinate or Coordinate(longitude=141.0, latitude=43.0),
        properties=_valid_properties(**overrides),
    )


def test_適合データの検証_validate_featuresが_全て適合していた場合_空リストを返す():
    # 必須非空・列挙値・都道府県整合・座標値域を満たすと違反ゼロであることを確認する
    features = [
        _valid_feature(),
        _valid_feature(
            coordinate=Coordinate(longitude=127.6, latitude=26.2),
            kind=FacilityKind.SAPA,
            pref_code="47",
            pref_name="沖縄県",
            direction=Direction.UP,
        ),
    ]

    assert validate_features(features) == []


def test_適合データの検証_validate_featuresが_空のFeature列だった場合_空リストを返す():
    # 入力が空でも例外なく空リストになることを確認する
    assert validate_features([]) == []


def test_戻り値型の検証_validate_featuresが_違反を検出した場合_ValidationIssueを返す():
    # 戻り値の要素がlocation付きのValidationIssueであることを確認する
    features = [_valid_feature(name="")]

    issues = validate_features(features)

    assert len(issues) == 1
    assert isinstance(issues[0], ValidationIssue)
    assert issues[0].location == "features[0].properties.name"
    assert issues[0].message


def test_必須項目の検証_validate_featuresが_施設名称が空だった場合_違反を報告する():
    # 必須文字列nameの非空違反が報告されることを確認する(2.1)
    features = [_valid_feature(name="   ")]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].properties.name" in locations


def test_必須項目の検証_validate_featuresが_都道府県名が空だった場合_違反を報告する():
    # 必須文字列pref_nameの非空違反が報告されることを確認する
    features = [_valid_feature(pref_name="")]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].properties.pref_name" in locations


def test_列挙値の検証_validate_featuresが_施設種別が不正だった場合_違反を報告する():
    # kindに列挙外の値が入ると違反として報告されることを確認する(2.3)
    features = [_valid_feature(kind="unknown_kind")]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].properties.kind" in locations


def test_列挙値の検証_validate_featuresが_上り下り区分が不正だった場合_違反を報告する():
    # directionに列挙外の値が入ると違反として報告されることを確認する
    features = [_valid_feature(direction="ななめ")]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].properties.direction" in locations


def test_列挙値の検証_validate_featuresが_列挙値の生文字列だった場合_違反を報告しない():
    # 05/06が正規化後の素の値(enumではなく文字列)を渡しても適合とみなすことを確認する
    features = [_valid_feature(kind="michinoeki", direction="上り")]

    assert validate_features(features) == []


def test_列挙値の検証_validate_featuresが_上り下り区分が未指定だった場合_違反を報告しない():
    # 任意項目directionがNoneのときは違反にならないことを確認する
    features = [_valid_feature(direction=None)]

    assert validate_features(features) == []


def test_列挙値の検証_validate_featuresが_削除状態が不正だった場合_違反を報告する():
    # statusに列挙外の値が入ると違反として報告されることを確認する(8.2, 8.3)
    features = [_valid_feature(status="unknown_status")]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].properties.status" in locations


def test_列挙値の検証_validate_featuresが_削除状態が既定値だった場合_違反を報告しない():
    # status既定(ACTIVE)では違反にならないことを確認する
    features = [_valid_feature(status=FacilityStatus.ACTIVE)]

    assert validate_features(features) == []


def test_都道府県整合の検証_validate_featuresが_都道府県番号が実在しない場合_違反を報告する():
    # 対応表に存在しないpref_codeが違反として報告されることを確認する(2.4)
    features = [_valid_feature(pref_code="99")]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].properties.pref_code" in locations


def test_都道府県整合の検証_validate_featuresが_番号と名称が不整合だった場合_違反を報告する():
    # 実在する番号でも名称が対応表と一致しなければ違反になることを確認する
    features = [_valid_feature(pref_code="01", pref_name="東京都")]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].properties.pref_name" in locations


def test_座標値域の検証_validate_featuresが_緯度が範囲外だった場合_違反を報告する():
    # 緯度が±90を超えると値域違反になることを確認する(3.3)
    features = [_valid_feature(coordinate=Coordinate(longitude=141.0, latitude=90.1))]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].coordinate.latitude" in locations


def test_座標値域の検証_validate_featuresが_経度が範囲外だった場合_違反を報告する():
    # 経度が±180を超えると値域違反になることを確認する(3.3)
    features = [_valid_feature(coordinate=Coordinate(longitude=-180.1, latitude=43.0))]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].coordinate.longitude" in locations


def test_座標値域の検証_validate_featuresが_緯度経度が境界値だった場合_違反を報告しない():
    # ±90・±180の境界値ちょうどは適合として扱うことを確認する
    features = [
        _valid_feature(coordinate=Coordinate(longitude=180.0, latitude=90.0)),
        _valid_feature(coordinate=Coordinate(longitude=-180.0, latitude=-90.0)),
    ]

    assert validate_features(features) == []


def test_座標値域の検証_validate_featuresが_座標がNaNだった場合_値域違反として報告する():
    # NaNは解釈できない座標として値域違反に含めることを確認する(3.3)
    features = [_valid_feature(coordinate=Coordinate(longitude=math.nan, latitude=43.0))]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].coordinate.longitude" in locations


def test_座標値域の検証_validate_featuresが_座標がinfだった場合_値域違反として報告する():
    # infも解釈できない座標として値域違反に含めることを確認する(3.3)
    features = [_valid_feature(coordinate=Coordinate(longitude=141.0, latitude=math.inf))]

    locations = [issue.location for issue in validate_features(features)]

    assert "features[0].coordinate.latitude" in locations


def test_網羅性の検証_validate_featuresが_1Featureに複数違反がある場合_全違反を報告する():
    # 最初の違反で打ち切らず、同一Feature内の全項目を走査することを確認する(5.2)
    features = [
        _valid_feature(
            name="",
            pref_name="",
            coordinate=Coordinate(longitude=200.0, latitude=100.0),
        )
    ]

    locations = {issue.location for issue in validate_features(features)}

    assert {
        "features[0].properties.name",
        "features[0].properties.pref_name",
        "features[0].coordinate.longitude",
        "features[0].coordinate.latitude",
    } <= locations


def test_網羅性の検証_validate_featuresが_複数Featureに違反がある場合_全Featureを走査する():
    # 違反Featureがあっても後続Featureの走査を続け、indexが違反箇所に反映されることを確認する
    features = [
        _valid_feature(),
        _valid_feature(name=""),
        _valid_feature(),
        _valid_feature(pref_code="99"),
    ]

    locations = {issue.location for issue in validate_features(features)}

    assert "features[1].properties.name" in locations
    assert "features[3].properties.pref_code" in locations


def test_無副作用の検証_validate_featuresが_違反を検出した場合_入力を変更しない():
    # 検証は報告のみで入力Feature列を変更しないことを確認する(副作用なし)
    original = _valid_feature(name="")
    features = [original]

    validate_features(features)

    assert features == [original]


def test_例外型の検証_ValidationIssueが_構築された場合_不変である():
    # ValidationIssueがfrozen dataclassであり構築後に変更できないことを確認する
    issue = ValidationIssue(location="features[0].properties.name", message="施設名称が空です")

    with pytest.raises((AttributeError, TypeError)):
        issue.location = "changed"  # type: ignore[misc]


# --- validate_filename(5.4) ---


def test_ファイル名検証_validate_filenameが_命名規則に適合していた場合_空リストを返す():
    # 命名規則に適合するファイル名では違反ゼロであることを確認する(5.4)
    assert validate_filename("01_hokkaido_michinoeki.geojson") == []


def test_ファイル名検証_validate_filenameが_命名規則に違反していた場合_違反を報告する():
    # パターン不一致のファイル名がlocation="filename"で報告されることを確認する(5.4)
    issues = validate_filename("hokkaido.geojson")

    assert len(issues) == 1
    assert isinstance(issues[0], ValidationIssue)
    assert issues[0].location == "filename"
    assert issues[0].message


def test_ファイル名検証_validate_filenameが_番号とローマ字が不整合だった場合_違反を報告する():
    # 実在番号でもローマ字名が対応表と不整合なら違反になることを確認する(5.4)
    issues = validate_filename("01_tokyo_michinoeki.geojson")

    assert [issue.location for issue in issues] == ["filename"]


# --- validate_index_consistency(6.1, 6.2, 6.4) ---


def _entry(path: str) -> IndexEntry:
    # 検証対象はpathのみのため、updated_atは固定値でよい
    return IndexEntry(path=path, updated_at=datetime(2026, 7, 12, tzinfo=UTC))


def test_index整合性の検証_validate_index_consistencyが_全pathが適合していた場合_空リストを返す():
    # 命名規則に適合するpathのみのindexでは違反ゼロであることを確認する(6.2)
    index = IndexData(
        files=(
            _entry("01_hokkaido_michinoeki.geojson"),
            _entry("47_okinawa_sapa.geojson"),
        )
    )

    assert validate_index_consistency(index) == []


def test_index整合性の検証_validate_index_consistencyが_空のindexだった場合_空リストを返す():
    # エントリが無いindexでも例外なく空リストになることを確認する
    assert validate_index_consistency(IndexData(files=())) == []


def test_index整合性の検証_validate_index_consistencyが_命名規則違反のpathを含む場合_違反を報告する():
    # 命名規則に適合しないpathがlocation付きで報告されることを確認する(6.4)
    index = IndexData(files=(_entry("broken.geojson"),))

    issues = validate_index_consistency(index)

    assert len(issues) == 1
    assert issues[0].location == "index.files[0].path"
    assert issues[0].message


def test_index整合性の検証_validate_index_consistencyが_複数の違反pathを含む場合_全違反を報告する():
    # 最初の違反で打ち切らず全エントリを走査し、indexが違反箇所に反映されることを確認する
    index = IndexData(
        files=(
            _entry("01_hokkaido_michinoeki.geojson"),
            _entry("broken.geojson"),
            _entry("48_unknown_sapa.geojson"),
        )
    )

    locations = [issue.location for issue in validate_index_consistency(index)]

    assert locations == ["index.files[1].path", "index.files[2].path"]


def test_無副作用の検証_validate_index_consistencyが_違反を検出した場合_入力を変更しない():
    # 検証は報告のみで入力indexを変更しないことを確認する(副作用なし)
    index = IndexData(files=(_entry("broken.geojson"),))
    original_files = index.files

    validate_index_consistency(index)

    assert index.files == original_files


def test_日時形式の検証_index_storeのupdated_atが_保存後に再読込された場合_ISO8601形式のdatetimeになる(tmp_path):
    # updated_atのISO 8601形式(6.3)はindex_storeのdatetime型で保証されていることを確認する
    index_path = tmp_path / "index.json"
    updated_at = datetime(2026, 7, 12, 9, 30, tzinfo=UTC)
    index = upsert_entry(IndexData(files=()), "01_hokkaido_michinoeki.geojson", updated_at)

    save_index(index, index_path)
    reloaded = load_index(index_path)

    # 再読込後もdatetime型として往復し、命名規則整合性検証も通過する
    assert isinstance(reloaded.files[0].updated_at, datetime)
    assert reloaded.files[0].updated_at == updated_at
    assert validate_index_consistency(reloaded) == []
