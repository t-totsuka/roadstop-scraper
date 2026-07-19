"""都道府県単位のグルーピング・マージ・出力・index更新(sapa.runner)の検証。

タスク5.1の観測可能な完了条件を検証する: 1サイト失敗時に当該サイト帰属の
前回施設が削除遷移せず維持されること、検証違反都道府県のみ出力されず他は
完了すること、出力成功時のみ管理ファイルが更新されること
(design.md「sapa.runner」Responsibilities、research.md「サイト単位の一覧取得
失敗は『当該サイトの前回データ現状維持』で隔離する」)。

``SapaSite``はプロトコルのため、テストでは``owns_url``/``key``のみを満たす
最小限の偽サイト(``_FakeSite``)を用いる(``tests/sapa/test_collector.py``の
偽オブジェクト方針と同様)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from roadstop_scraper.common import index_store
from roadstop_scraper.geojson import (
    PREFECTURES,
    Coordinate,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    FacilityStatus,
    GeoJsonValidationError,
    ValidationIssue,
    build_geojson_filename,
    read_geojson,
    write_geojson,
)
from roadstop_scraper.sapa.collector import SiteCollectResult
from roadstop_scraper.sapa.runner import SapaPrefectureResult, run_prefecture, run_prefectures

_CONFIRMED_AT = datetime(2026, 7, 19, 9, 0, 0, tzinfo=UTC)
_PREVIOUS_CONFIRMED_AT = datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)

_TOKYO = next(p for p in PREFECTURES if p.code == "13")
_KANAGAWA = next(p for p in PREFECTURES if p.code == "14")


@dataclass
class _FakeSite:
    """``owns_url``/``key``のみを満たす偽サイト(URLプレフィックスで帰属判定)。"""

    key: str
    owned_prefixes: tuple[str, ...] = field(default_factory=tuple)
    listing_kind: str = "html"

    def owns_url(self, url: str) -> bool:
        return any(url.startswith(prefix) for prefix in self.owned_prefixes)

    def listing_urls(self, prefectures):  # pragma: no cover - runnerからは呼ばれない
        raise NotImplementedError

    def parse_listing(self, content):  # pragma: no cover
        raise NotImplementedError

    def extract_detail(self, page, detail_url):  # pragma: no cover
        raise NotImplementedError


_SITE_A = _FakeSite(key="site-a", owned_prefixes=("https://site-a.example/",))
_SITE_B = _FakeSite(key="site-b", owned_prefixes=("https://site-b.example/",))
_ALL_SITES = (_SITE_A, _SITE_B)


def _feature(
    *,
    name: str,
    source_url: str,
    pref: object = _TOKYO,
    status: FacilityStatus = FacilityStatus.ACTIVE,
    last_confirmed_at: datetime | None = None,
    coordinate: Coordinate | None = None,
) -> FacilityFeature:
    return FacilityFeature(
        coordinate=coordinate if coordinate is not None else Coordinate(longitude=139.0, latitude=35.0),
        properties=FacilityProperties(
            name=name,
            kind=FacilityKind.SAPA,
            pref_code=pref.code,
            pref_name=pref.name_ja,
            source_url=source_url,
            status=status,
            last_confirmed_at=last_confirmed_at,
        ),
    )


def test_サイト失敗隔離の検証_失敗サイト帰属の前回施設は削除遷移せず現状維持で出力される(tmp_path):
    """research.md「サイト単位の一覧取得失敗は現状維持で隔離する」の核心。

    前回GeoJSONにサイトA帰属・サイトB帰属の2施設が存在する状態で、今回は
    サイトAが成功(新規データあり)・サイトBが失敗(failed_site_keysに含まれる)
    という状況を作る。listed_urlsにサイトBの施設URLを含めないことで、もし
    誤ってmerge_with_previousへ渡されていれば削除状態へ遷移してしまう
    (検出用の罠)ことを利用し、実装がサイトB施設をmergeの外側で現状維持のまま
    出力していることを検証する。
    """
    url_a = "https://site-a.example/1"
    url_b = "https://site-b.example/1"
    previous_a = _feature(
        name="施設A", source_url=url_a, status=FacilityStatus.ACTIVE, last_confirmed_at=_PREVIOUS_CONFIRMED_AT
    )
    previous_b = _feature(
        name="施設B", source_url=url_b, status=FacilityStatus.ACTIVE, last_confirmed_at=_PREVIOUS_CONFIRMED_AT
    )
    output_dir = tmp_path / "geo-json"
    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    write_geojson([previous_a, previous_b], filename, output_dir=output_dir)

    # 今回: サイトAは施設Aを再度確認(listed_urlsにurl_aを含む)。サイトBは
    # 失敗のため、今回のfeatures/listed_urlsにurl_bは一切含まれない。
    new_features = [
        _feature(name="施設A", source_url=url_a, status=FacilityStatus.ACTIVE, last_confirmed_at=_CONFIRMED_AT)
    ]
    listed_urls = frozenset({url_a})
    failed_site_keys = {"site-b"}

    result = run_prefecture(
        _TOKYO,
        new_features,
        listed_urls,
        failed_site_keys,
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert isinstance(result, SapaPrefectureResult)
    # サイトBの施設は削除判定に一切参加していないため、遷移カウントは0。
    assert result.newly_deleted_count == 0

    written = read_geojson(output_dir / filename)
    feature_b = next(f for f in written if f.properties.source_url == url_b)
    # 現状維持: statusもlast_confirmed_atも前回のまま変化しない。
    assert feature_b.properties.status is FacilityStatus.ACTIVE
    assert feature_b.properties.last_confirmed_at == _PREVIOUS_CONFIRMED_AT

    feature_a = next(f for f in written if f.properties.source_url == url_a)
    assert feature_a.properties.status is FacilityStatus.ACTIVE
    assert feature_a.properties.last_confirmed_at == _CONFIRMED_AT


def test_通常削除遷移の検証_成功サイト帰属の前回施設は一覧から消失すると削除状態へ遷移する(tmp_path):
    url_a = "https://site-a.example/1"
    previous_a = _feature(
        name="施設A", source_url=url_a, status=FacilityStatus.ACTIVE, last_confirmed_at=_PREVIOUS_CONFIRMED_AT
    )
    output_dir = tmp_path / "geo-json"
    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    write_geojson([previous_a], filename, output_dir=output_dir)

    # サイトAは成功しているが、施設Aは今回の一覧・新規結果のいずれにも含まれない
    # (一覧から消失した状況)。
    result = run_prefecture(
        _TOKYO,
        [],
        frozenset(),
        set(),
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert isinstance(result, SapaPrefectureResult)
    assert result.newly_deleted_count == 1

    written = read_geojson(output_dir / filename)
    feature_a = next(f for f in written if f.properties.source_url == url_a)
    assert feature_a.properties.status is FacilityStatus.DELETED


def test_孤児施設の検証_どのサイトにも帰属しない前回施設は通常の削除判定に含まれる(tmp_path):
    url_orphan = "https://removed-site.example/1"
    previous_orphan = _feature(
        name="孤児施設",
        source_url=url_orphan,
        status=FacilityStatus.ACTIVE,
        last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
    )
    output_dir = tmp_path / "geo-json"
    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    write_geojson([previous_orphan], filename, output_dir=output_dir)

    # どのサイトのowns_urlにも一致しない(_ALL_SITESのプレフィックスと不一致)。
    # 今回の一覧にもURLが含まれないため、通常の削除判定で削除状態へ遷移する。
    result = run_prefecture(
        _TOKYO,
        [],
        frozenset(),
        set(),
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert isinstance(result, SapaPrefectureResult)
    assert result.newly_deleted_count == 1
    written = read_geojson(output_dir / filename)
    feature_orphan = next(f for f in written if f.properties.source_url == url_orphan)
    assert feature_orphan.properties.status is FacilityStatus.DELETED


def test_検証違反隔離の検証_出力前検証違反時に当該都道府県のみ中断されファイルもindexも更新されない(
    tmp_path, monkeypatch
):
    output_dir = tmp_path / "geo-json"

    def _raise_validation_error(*_args, **_kwargs):
        raise GeoJsonValidationError([ValidationIssue(location="features[0]", message="検証違反(意図的)")])

    monkeypatch.setattr("roadstop_scraper.sapa.runner.write_geojson", _raise_validation_error)

    new_features = [_feature(name="施設A", source_url="https://site-a.example/1")]
    result = run_prefecture(
        _TOKYO,
        new_features,
        frozenset({"https://site-a.example/1"}),
        set(),
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert result is None
    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    assert not (output_dir / filename).exists()
    assert not (output_dir / "index.json").exists()


def test_検証違反隔離の検証_一つの都道府県が検証違反でも他の都道府県は正常に完了する(tmp_path, monkeypatch):
    output_dir = tmp_path / "geo-json"
    tokyo_filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    real_write_geojson = write_geojson

    def _fail_only_tokyo(features, filename, output_dir=None, **kwargs):
        if filename == tokyo_filename:
            raise GeoJsonValidationError([ValidationIssue(location="features[0]", message="検証違反(意図的)")])
        return real_write_geojson(features, filename, output_dir=output_dir, **kwargs)

    monkeypatch.setattr("roadstop_scraper.sapa.runner.write_geojson", _fail_only_tokyo)

    tokyo_feature = _feature(name="施設東京", source_url="https://site-a.example/1", pref=_TOKYO)
    kanagawa_feature = _feature(name="施設神奈川", source_url="https://site-a.example/2", pref=_KANAGAWA)
    site_result = SiteCollectResult(
        site_key="site-a",
        features=(tokyo_feature, kanagawa_feature),
        listed_urls=frozenset({"https://site-a.example/1", "https://site-a.example/2"}),
        skipped_counts={},
        geocoded_counts={},
    )

    results = run_prefectures(
        [_TOKYO, _KANAGAWA],
        [site_result],
        set(),
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert results[0] is None
    assert isinstance(results[1], SapaPrefectureResult)

    assert not (output_dir / tokyo_filename).exists()
    kanagawa_filename = build_geojson_filename(_KANAGAWA, FacilityKind.SAPA)
    written = read_geojson(output_dir / kanagawa_filename)
    assert [f.properties.name for f in written] == ["施設神奈川"]

    index = index_store.load_index(output_dir / "index.json")
    assert {entry.path for entry in index.files} == {kanagawa_filename}


def test_前回ファイル破損の検証_前回GeoJSONが破損している場合当該都道府県のみ中断されファイルが上書きされない(tmp_path):
    output_dir = tmp_path / "geo-json"
    output_dir.mkdir(parents=True)
    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    corrupted_content = "{ this is not valid json"
    (output_dir / filename).write_text(corrupted_content, encoding="utf-8")

    result = run_prefecture(
        _TOKYO,
        [],
        frozenset(),
        set(),
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert result is None
    assert (output_dir / filename).read_text(encoding="utf-8") == corrupted_content
    assert not (output_dir / "index.json").exists()


def test_正常完了の検証_前回ファイルなしで新規施設がある場合にGeoJSON出力とindex更新が正しく行われる(tmp_path):
    output_dir = tmp_path / "geo-json"
    new_features = [_feature(name="新規施設", source_url="https://site-a.example/1")]

    result = run_prefecture(
        _TOKYO,
        new_features,
        frozenset({"https://site-a.example/1"}),
        set(),
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert isinstance(result, SapaPrefectureResult)
    assert result.prefecture == _TOKYO
    assert result.scraped_count == 1
    assert result.reactivated_count == 0
    assert result.newly_deleted_count == 0
    assert result.purged_count == 0

    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    output_path = output_dir / filename
    assert output_path.exists()

    written = read_geojson(output_path)
    assert len(written) == 1
    assert written[0].properties.name == "新規施設"
    assert written[0].properties.status is FacilityStatus.ACTIVE
    assert written[0].properties.last_confirmed_at == _CONFIRMED_AT

    index = index_store.load_index(output_dir / "index.json")
    assert len(index.files) == 1
    assert index.files[0].path == filename
    assert index.files[0].updated_at == _CONFIRMED_AT


def test_全都道府県処理の検証_今回新規データが無い都道府県も既存の前回施設が削除遷移するまで処理される(tmp_path):
    """design.md「範囲内都道府県のファイルのみを読み書きする」: 今回0件の新規
    検出であっても、前回出力済みの施設がある都道府県はrun_prefecturesの対象
    となり、通常の削除判定(サイトA成功帰属・listed_urls不在で削除)が行われる
    ことを検証する。
    """
    output_dir = tmp_path / "geo-json"
    kanagawa_filename = build_geojson_filename(_KANAGAWA, FacilityKind.SAPA)
    previous_feature = _feature(
        name="神奈川の前回施設",
        source_url="https://site-a.example/kanagawa-1",
        pref=_KANAGAWA,
        status=FacilityStatus.ACTIVE,
        last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
    )
    write_geojson([previous_feature], kanagawa_filename, output_dir=output_dir)

    # 今回、site-aは東京の施設のみを新規収集し、神奈川については何も収集しない
    # (listed_urlsにも神奈川の前回施設URLは含まれない)。
    site_result = SiteCollectResult(
        site_key="site-a",
        features=(_feature(name="施設東京", source_url="https://site-a.example/tokyo-1", pref=_TOKYO),),
        listed_urls=frozenset({"https://site-a.example/tokyo-1"}),
        skipped_counts={},
        geocoded_counts={},
    )

    results = run_prefectures(
        [_TOKYO, _KANAGAWA],
        [site_result],
        set(),
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert isinstance(results[0], SapaPrefectureResult)
    assert isinstance(results[1], SapaPrefectureResult)
    # 神奈川は今回新規0件だが、前回施設がlisted_urlsに含まれないため削除遷移する。
    assert results[1].newly_deleted_count == 1

    written = read_geojson(output_dir / kanagawa_filename)
    feature = next(f for f in written if f.properties.source_url == "https://site-a.example/kanagawa-1")
    assert feature.properties.status is FacilityStatus.DELETED


def test_グルーピングの検証_複数サイトの成功結果が都道府県ごとに正しく集約されlisted_urlsは全サイトの和集合になる(
    tmp_path,
):
    """design.md「listed_urlsは成功サイトの和集合」: 複数の成功SiteCollectResult
    (別サイト)を横断して、pref_codeで正しく都道府県バケットへ振り分けられる
    こと、listed_urlsが全サイトの和集合として渡されること(一方のサイトにしか
    存在しないURLでも、他方サイトの前回施設のマージ判定には影響しないこと)を
    検証する。
    """
    output_dir = tmp_path / "geo-json"

    site_a_result = SiteCollectResult(
        site_key="site-a",
        features=(_feature(name="施設A", source_url="https://site-a.example/1", pref=_TOKYO),),
        listed_urls=frozenset({"https://site-a.example/1"}),
        skipped_counts={},
        geocoded_counts={},
    )
    site_b_result = SiteCollectResult(
        site_key="site-b",
        features=(_feature(name="施設B", source_url="https://site-b.example/1", pref=_TOKYO),),
        listed_urls=frozenset({"https://site-b.example/1"}),
        skipped_counts={},
        geocoded_counts={},
    )

    results = run_prefectures(
        [_TOKYO],
        [site_a_result, site_b_result],
        set(),
        _ALL_SITES,
        _CONFIRMED_AT,
        output_dir=output_dir,
    )

    assert len(results) == 1
    assert isinstance(results[0], SapaPrefectureResult)
    assert results[0].scraped_count == 2

    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    written = read_geojson(output_dir / filename)
    names = {f.properties.name for f in written}
    assert names == {"施設A", "施設B"}
    for feature in written:
        assert feature.properties.status is FacilityStatus.ACTIVE
