"""都道府県単位のグルーピング・マージ・出力・index更新(sapa.runner)の検証。

タスク5.1の観測可能な完了条件を検証する: 1サイト失敗時に当該サイト帰属の
前回施設が削除遷移せず維持されること、検証違反都道府県のみ出力されず他は
完了すること、出力成功時のみ管理ファイルが更新されること
(design.md「sapa.runner」Responsibilities、research.md「サイト単位の一覧取得
失敗は『当該サイトの前回データ現状維持』で隔離する」)。

``SapaSite``はプロトコルのため、テストでは``owns_url``/``key``のみを満たす
最小限の偽サイト(``_FakeSite``)を用いる(``tests/sapa/test_collector.py``の
偽オブジェクト方針と同様)。

タスク5.2で、範囲全体のオーケストレーション``run_scope``の観測可能な完了条件を
追加検証する: 範囲解決が不正な場合に通信発生前に例外が伝播すること、全サイト・
全都道府県成功時のみレジューム状態と部分結果キャッシュがクリアされること、
1サイトが一覧取得失敗しても他サイトの収集が継続されレジュームはクリアされない
こと、1都道府県が出力前検証違反で失敗した場合も同様であること、集計ログの件数が
処理結果と一致すること、``confirmed_at``が1回の呼び出しにつき1つのスナップ
ショットとして全都道府県へ一貫して渡されること。``run_scope``レベルのテストは
``collect_site``自体の詳細な振る舞い(``tests/sapa/test_collector.py``が担当)を
再検証せず、``tests/sapa/test_collector.py``の偽フェッチャー・偽サイト方針を
踏襲した偽オブジェクトで純粋なオーケストレーション(結合)のみを検証する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from roadstop_scraper.common import index_store
from roadstop_scraper.common.resume_store import ResumeStore
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
from roadstop_scraper.pipeline import InvalidScopeError, ScopeSpec
from roadstop_scraper.sapa.collector import SapaPartialStore, SiteCollectResult
from roadstop_scraper.sapa.runner import (
    SapaPrefectureResult,
    SapaScopeRunResult,
    run_prefecture,
    run_prefectures,
    run_scope,
)
from roadstop_scraper.sapa.sites import SapaDetail, SapaListingResult, SapaStub
from roadstop_scraper.scraping import FetchedContent, FetchFailedError, UrlResumeTracker

_CONFIRMED_AT = datetime(2026, 7, 19, 9, 0, 0, tzinfo=UTC)
_PREVIOUS_CONFIRMED_AT = datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)
_RETENTION_EXCEEDED_CONFIRMED_AT = datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)

_TOKYO = next(p for p in PREFECTURES if p.code == "13")
_KANAGAWA = next(p for p in PREFECTURES if p.code == "14")
_TOKUSHIMA = next(p for p in PREFECTURES if p.code == "36")
_KAGAWA = next(p for p in PREFECTURES if p.code == "37")
_EHIME = next(p for p in PREFECTURES if p.code == "38")
_KOCHI = next(p for p in PREFECTURES if p.code == "39")


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


# ---------------------------------------------------------------------------
# タスク5.2: run_scope(範囲全体のオーケストレーション)の検証。
#
# tests/sapa/test_collector.pyの偽オブジェクト方針(SapaSiteプロトコルを満たす
# 偽サイト・fetch_text/fetch_jsonの最小限を満たす偽フェッチャー・geocode(address)
# のみを満たす偽ジオコーダー)を踏襲するが、run_scopeレベルでは複数サイト・
# 複数都道府県・resume/partial_storeのクリア可否まで検証するため、本ファイル
# 専用の偽オブジェクトとして再定義する(test_collector.pyの偽オブジェクトは
# モジュール非公開でimportできないため、既存の方針にならい重複実装する)。
# ---------------------------------------------------------------------------


@dataclass
class _RunScopeFakeSite:
    """``SapaSite``プロトコルを満たす偽サイト(``run_scope``結合テスト用)。

    ``tests/sapa/test_collector.py``の``_FakeSite``と同じ方針(実HTML解析は
    行わず、``parse_listing``/``extract_detail``へ事前登録した結果をそのまま
    返す)に加え、``owns_url``をURLプレフィックスで判定する(前回施設の
    サイト帰属判定に必要)。
    """

    key: str
    owned_prefix: str
    listing_kind: str = "json"
    listing_url_list: tuple[str, ...] = ()
    listing_by_url: dict[str, SapaListingResult] = field(default_factory=dict)
    details_by_url: dict[str, SapaDetail | Exception] = field(default_factory=dict)

    def owns_url(self, url: str) -> bool:
        return url.startswith(self.owned_prefix)

    def listing_urls(self, prefectures: object) -> tuple[str, ...]:
        return self.listing_url_list

    def parse_listing(self, content: object) -> SapaListingResult:
        if self.listing_kind == "json":
            assert isinstance(content, SapaListingResult)
            return content
        return self.listing_by_url[content.url]  # type: ignore[attr-defined]

    def extract_detail(self, page: object, detail_url: str) -> SapaDetail:
        result = self.details_by_url[detail_url]
        if isinstance(result, Exception):
            raise result
        return result


@dataclass
class _RunScopeFakeFetcher:
    """事前登録した応答(またはraiseすべき例外)をURLごとに返す偽フェッチャー。

    ``collect_site``は``fetch_text``(詳細ページ、および一覧が
    ``listing_kind == "html"``の場合)と``fetch_json``(一覧が
    ``listing_kind == "json"``の場合)のみを呼び出すため、その最小インタ
    フェースのみを満たす。
    """

    text_by_url: dict[str, str] = field(default_factory=dict)
    json_by_url: dict[str, object] = field(default_factory=dict)
    raise_by_url: dict[str, Exception] = field(default_factory=dict)
    text_calls: list[str] = field(default_factory=list)
    json_calls: list[str] = field(default_factory=list)

    def fetch_text(self, url: str) -> FetchedContent:
        self.text_calls.append(url)
        if url in self.raise_by_url:
            raise self.raise_by_url[url]
        return FetchedContent(url=url, text=self.text_by_url.get(url, "<html></html>"), encoding="utf-8")

    def fetch_json(self, url: str) -> object:
        self.json_calls.append(url)
        if url in self.raise_by_url:
            raise self.raise_by_url[url]
        return self.json_by_url.get(url)


@dataclass
class _RunScopeFakeGeocoder:
    """住所ごとに座標(またはNone)を返す偽ジオコーダー。

    ``fail_addresses``に含まれる住所は座標解決不可(``None``)として扱い、
    それ以外は``result``をそのまま返す(4.2の座標補完・4.3の補完不可スキップ
    双方を1つの偽物で再現するため)。
    """

    result: Coordinate | None = None
    fail_addresses: frozenset[str] = frozenset()
    calls: list[str] = field(default_factory=list)

    def geocode(self, address: str) -> Coordinate | None:
        self.calls.append(address)
        if address in self.fail_addresses:
            return None
        return self.result


class _NeverCalledFetcher:
    """1.4検証用: 呼ばれたら即座に失敗する偽フェッチャー(HTTP相当呼び出しの監視)。"""

    def fetch_text(self, url: str) -> FetchedContent:
        raise AssertionError(f"resolve_scope失敗後にfetch_textが呼ばれた: {url}")

    def fetch_json(self, url: str) -> object:
        raise AssertionError(f"resolve_scope失敗後にfetch_jsonが呼ばれた: {url}")


class _NeverCalledGeocoder:
    """1.4検証用: 呼ばれたら即座に失敗する偽ジオコーダー。"""

    def geocode(self, address: str) -> Coordinate | None:
        raise AssertionError(f"resolve_scope失敗後にgeocodeが呼ばれた: {address}")


class _NeverCalledSite:
    """1.4検証用: ``SapaSite``プロトコルのいずれのメソッドが呼ばれても失敗する偽サイト。

    ``resolve_scope``失敗時に``ALL_SITES``の反復すら開始されないことを、
    フェッチャー呼び出し監視に加えて二重に保証する。
    """

    key = "never-called"
    listing_kind = "json"

    def owns_url(self, url: str) -> bool:
        raise AssertionError(f"resolve_scope失敗後にowns_urlが呼ばれた: {url}")

    def listing_urls(self, prefectures: object) -> tuple[str, ...]:
        raise AssertionError("resolve_scope失敗後にlisting_urlsが呼ばれた")

    def parse_listing(self, content: object) -> SapaListingResult:
        raise AssertionError("resolve_scope失敗後にparse_listingが呼ばれた")

    def extract_detail(self, page: object, detail_url: str) -> SapaDetail:
        raise AssertionError(f"resolve_scope失敗後にextract_detailが呼ばれた: {detail_url}")


def _sapa_detail(
    *,
    name: str = "テストSA",
    road_name: str | None = "テスト自動車道",
    address: str | None,
    coordinate: Coordinate | None = None,
) -> SapaDetail:
    return SapaDetail(
        name=name,
        road_name=road_name,
        direction=None,
        area_direction=None,
        address=address,
        postal_code=None,
        tel=None,
        opening_hours=None,
        parking=None,
        websites=(),
        facilities=(),
        coordinate=coordinate,
    )


def test_範囲解決の検証_不正なScopeSpecの場合_InvalidScopeErrorが伝播しどのフェッチャーもサイトも一切呼ばれない(
    tmp_path, monkeypatch
):
    """1.4: regionとprefecture_codeの同時指定でresolve_scopeがInvalidScopeErrorを
    送出するケースで、run_scopeがそのまま例外を伝播し、フェッチャー・
    ジオコーダー・サイトいずれのHTTP相当呼び出しも一切発生しないことを検証する
    (design.md「1.4: HTTP発生前にresolve_scope」、michinoeki.runner.run_scopeの
    同名テストと同じ検証方針)。
    """
    monkeypatch.setattr("roadstop_scraper.sapa.runner.ALL_SITES", (_NeverCalledSite(),))
    resume_store = ResumeStore(state_dir=tmp_path / ".resume")

    with pytest.raises(InvalidScopeError):
        run_scope(
            ScopeSpec(region="kanto", prefecture_code="13"),
            fetcher=_NeverCalledFetcher(),
            geocoder=_NeverCalledGeocoder(),
            resume=UrlResumeTracker("sapa-test-invalid-scope", store=resume_store),
            partial_result_store=SapaPartialStore(store=resume_store),
        )


def test_全体成功の検証_全サイト全都道府県成功時にレジュームと部分結果がクリアされ集計ログの件数が処理結果と一致する(
    tmp_path, caplog, monkeypatch
):
    """7.3, 10.1: 四国地方(徳島・香川・愛媛・高知)を対象範囲とし、単一サイトが
    新規施設・削除復帰(reactivated)・保持期間超過の完全除去(purged)・座標
    補完(geocoded)・座標解決不可のスキップ(skipped)・一覧消失による新規削除
    (newly_deleted)の全パターンを1回の実行に含む状況を作る。全都道府県の出力が
    成功するため、resume/partial_storeの両方がクリアされ、集計ログの各件数が
    ``SapaScopeRunResult.prefecture_results``の合算値と一致することを検証する。
    """
    output_dir = tmp_path / "geo-json"

    url_toku_new = "https://site-a.example/tokushima-1"
    url_toku_reactivate = "https://site-a.example/tokushima-old"
    url_kagawa_new = "https://site-a.example/kagawa-1"
    url_ehime_fail = "https://site-a.example/ehime-1"
    url_kagawa_purge_candidate = "https://site-a.example/kagawa-old"
    url_kochi_delete_candidate = "https://site-a.example/kochi-old"

    ehime_address = f"{_EHIME.name_ja}松山市本町1-1"

    # 前回出力: 徳島(削除済み→今回再出現で復帰)・香川(削除済み・保持期間超過→
    # 完全除去)・高知(有効→今回一覧から消失し新規削除)。愛媛は前回出力なし。
    write_geojson(
        [
            _feature(
                name="施設徳島(旧)",
                source_url=url_toku_reactivate,
                pref=_TOKUSHIMA,
                status=FacilityStatus.DELETED,
                last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
            )
        ],
        build_geojson_filename(_TOKUSHIMA, FacilityKind.SAPA),
        output_dir=output_dir,
    )
    write_geojson(
        [
            _feature(
                name="施設香川(旧・保持期間超過)",
                source_url=url_kagawa_purge_candidate,
                pref=_KAGAWA,
                status=FacilityStatus.DELETED,
                last_confirmed_at=_RETENTION_EXCEEDED_CONFIRMED_AT,
            )
        ],
        build_geojson_filename(_KAGAWA, FacilityKind.SAPA),
        output_dir=output_dir,
    )
    write_geojson(
        [
            _feature(
                name="施設高知(旧)",
                source_url=url_kochi_delete_candidate,
                pref=_KOCHI,
                status=FacilityStatus.ACTIVE,
                last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
            )
        ],
        build_geojson_filename(_KOCHI, FacilityKind.SAPA),
        output_dir=output_dir,
    )

    site_a = _RunScopeFakeSite(
        key="site-a",
        owned_prefix="https://site-a.example/",
        listing_kind="json",
        listing_url_list=("https://site-a.example/listing",),
        details_by_url={
            url_toku_new: _sapa_detail(
                name="施設徳島新規",
                address=f"{_TOKUSHIMA.name_ja}徳島市内町1-1",
                coordinate=Coordinate(longitude=134.5, latitude=34.1),
            ),
            url_toku_reactivate: _sapa_detail(
                name="施設徳島復活",
                address=f"{_TOKUSHIMA.name_ja}徳島市寺島本町1-1",
                coordinate=Coordinate(longitude=134.6, latitude=34.2),
            ),
            url_kagawa_new: _sapa_detail(
                name="施設香川",
                address=f"{_KAGAWA.name_ja}高松市サンポート1-1",
                coordinate=None,  # 直接座標なし→ジオコーディングで補完(4.2)
            ),
            url_ehime_fail: _sapa_detail(
                name="施設愛媛(座標不可)",
                address=ehime_address,
                coordinate=None,  # 直接座標なし・ジオコーディングも失敗(4.3)
            ),
        },
    )
    fetcher = _RunScopeFakeFetcher(
        json_by_url={
            "https://site-a.example/listing": SapaListingResult(
                stubs=(
                    SapaStub(display_name="a", detail_url=url_toku_new),
                    SapaStub(display_name="b", detail_url=url_toku_reactivate),
                    SapaStub(display_name="c", detail_url=url_kagawa_new),
                    SapaStub(display_name="d", detail_url=url_ehime_fail),
                ),
                listed_urls=frozenset({url_toku_new, url_toku_reactivate, url_kagawa_new, url_ehime_fail}),
                skipped_count=0,
            ),
        }
    )
    geocoder = _RunScopeFakeGeocoder(
        result=Coordinate(longitude=134.05, latitude=34.34),
        fail_addresses=frozenset({ehime_address}),
    )

    resume_store = ResumeStore(state_dir=tmp_path / ".resume")
    resume_key = "sapa-test-all-success"
    resume = UrlResumeTracker(resume_key, store=resume_store)
    partial_store = SapaPartialStore(store=resume_store)

    caplog.set_level("INFO")
    monkeypatch.setattr("roadstop_scraper.sapa.runner.ALL_SITES", (site_a,))

    result = run_scope(
        ScopeSpec(region="shikoku"),
        fetcher=fetcher,
        geocoder=geocoder,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_store,
    )

    assert isinstance(result, SapaScopeRunResult)
    assert result.failed_site_keys == frozenset()
    assert result.failed_prefecture_codes == frozenset()
    assert len(result.prefecture_results) == 4
    assert all(isinstance(r, SapaPrefectureResult) for r in result.prefecture_results)

    by_code = {r.prefecture.code: r for r in result.prefecture_results}
    assert by_code["36"].scraped_count == 2  # 徳島: 新規+復活
    assert by_code["36"].reactivated_count == 1
    assert by_code["36"].newly_deleted_count == 0
    assert by_code["36"].purged_count == 0

    assert by_code["37"].scraped_count == 1  # 香川: 新規(補完座標)
    assert by_code["37"].geocoded_count == 1
    assert by_code["37"].purged_count == 1  # 保持期間超過の前回削除済み施設

    assert by_code["38"].scraped_count == 0  # 愛媛: 座標解決不可でスキップ
    assert by_code["38"].skipped_count == 1

    assert by_code["39"].scraped_count == 0  # 高知: 一覧消失で新規削除
    assert by_code["39"].newly_deleted_count == 1

    # 7.3: 全サイト・全都道府県成功のため、resume/partial_storeともにクリアされる。
    assert resume_store.load(resume_key) is None
    reloaded_partial = SapaPartialStore(store=resume_store)
    assert reloaded_partial.features == []
    assert reloaded_partial.skipped_counts == {}
    assert reloaded_partial.geocoded_counts == {}

    # 10.1: 集計ログの件数がprefecture_resultsの合算値と一致する。
    expected_scraped = sum(r.scraped_count for r in result.prefecture_results if r is not None)
    expected_skipped = sum(r.skipped_count for r in result.prefecture_results if r is not None)
    expected_geocoded = sum(r.geocoded_count for r in result.prefecture_results if r is not None)
    expected_reactivated = sum(r.reactivated_count for r in result.prefecture_results if r is not None)
    expected_newly_deleted = sum(r.newly_deleted_count for r in result.prefecture_results if r is not None)
    expected_purged = sum(r.purged_count for r in result.prefecture_results if r is not None)
    assert expected_scraped == 3
    assert expected_skipped == 1
    assert expected_geocoded == 1
    assert expected_reactivated == 1
    assert expected_newly_deleted == 1
    assert expected_purged == 1

    assert f"scraped={expected_scraped}" in caplog.text
    assert f"skipped={expected_skipped}" in caplog.text
    assert f"geocoded={expected_geocoded}" in caplog.text
    assert f"reactivated={expected_reactivated}" in caplog.text
    assert f"newly_deleted={expected_newly_deleted}" in caplog.text
    assert f"purged={expected_purged}" in caplog.text
    assert "failed_sites=0" in caplog.text
    assert "failed_prefectures=0" in caplog.text


def test_サイト失敗の検証_一部サイトが一覧取得失敗でも他サイトの収集は継続しレジュームはクリアされない(
    tmp_path, monkeypatch
):
    """2.3, 7.3: サイトBの一覧取得が失敗(FetchFailedError)する状況で、サイトAの
    収集が正常に継続され東京都のGeoJSONへ反映されること、失敗したサイトBの
    識別子が``failed_site_keys``へ記録されること、1サイトでも失敗が残るため
    resume/partial_storeがクリアされないことを検証する。
    """
    output_dir = tmp_path / "geo-json"
    tokyo_detail_url = "https://site-a.example/tokyo-1"
    tokyo_address = f"{_TOKYO.name_ja}千代田1-1"

    site_a = _RunScopeFakeSite(
        key="site-a",
        owned_prefix="https://site-a.example/",
        listing_kind="json",
        listing_url_list=("https://site-a.example/listing",),
        details_by_url={
            tokyo_detail_url: _sapa_detail(
                name="施設東京",
                address=tokyo_address,
                coordinate=Coordinate(longitude=139.75, latitude=35.68),
            ),
        },
    )
    site_b = _RunScopeFakeSite(
        key="site-b",
        owned_prefix="https://site-b.example/",
        listing_kind="json",
        listing_url_list=("https://site-b.example/listing",),
    )
    fetcher = _RunScopeFakeFetcher(
        json_by_url={
            "https://site-a.example/listing": SapaListingResult(
                stubs=(SapaStub(display_name="a", detail_url=tokyo_detail_url),),
                listed_urls=frozenset({tokyo_detail_url}),
                skipped_count=0,
            ),
        },
        raise_by_url={
            "https://site-b.example/listing": FetchFailedError("https://site-b.example/listing", 503, 3),
        },
    )
    monkeypatch.setattr("roadstop_scraper.sapa.runner.ALL_SITES", (site_a, site_b))

    resume_store = ResumeStore(state_dir=tmp_path / ".resume")
    resume_key = "sapa-test-site-failure"
    resume = UrlResumeTracker(resume_key, store=resume_store)
    partial_store = SapaPartialStore(store=resume_store)

    result = run_scope(
        ScopeSpec(prefecture_code="13"),
        fetcher=fetcher,
        geocoder=_RunScopeFakeGeocoder(),
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_store,
    )

    assert result.failed_site_keys == frozenset({"site-b"})
    assert result.failed_prefecture_codes == frozenset()

    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    written = read_geojson(output_dir / filename)
    assert [f.properties.name for f in written] == ["施設東京"]

    # 1件でもサイト失敗が残るためresume/partial_storeはクリアされない。
    assert resume_store.load(resume_key) is not None
    reloaded_resume = UrlResumeTracker(resume_key, store=resume_store)
    assert reloaded_resume.is_processed(tokyo_detail_url) is True


def test_都道府県失敗の検証_一つの都道府県が出力前検証違反でも他は成功しレジュームはクリアされない(
    tmp_path, monkeypatch
):
    """6.2, 7.3: 単一サイトが四国4県すべてで一覧取得に成功するが、香川県の
    ``write_geojson``のみが検証違反で失敗する状況で、香川県のコードが
    ``failed_prefecture_codes``へ記録されること、他3県は正常に完了すること、
    1都道府県でも失敗が残るためresume/partial_storeがクリアされないことを
    検証する。
    """
    output_dir = tmp_path / "geo-json"
    url_toku = "https://site-a.example/tokushima-1"

    site_a = _RunScopeFakeSite(
        key="site-a",
        owned_prefix="https://site-a.example/",
        listing_kind="json",
        listing_url_list=("https://site-a.example/listing",),
        details_by_url={
            url_toku: _sapa_detail(
                name="施設徳島",
                address=f"{_TOKUSHIMA.name_ja}徳島市内町1-1",
                coordinate=Coordinate(longitude=134.5, latitude=34.1),
            ),
        },
    )
    fetcher = _RunScopeFakeFetcher(
        json_by_url={
            "https://site-a.example/listing": SapaListingResult(
                stubs=(SapaStub(display_name="a", detail_url=url_toku),),
                listed_urls=frozenset({url_toku}),
                skipped_count=0,
            ),
        }
    )
    monkeypatch.setattr("roadstop_scraper.sapa.runner.ALL_SITES", (site_a,))

    kagawa_filename = build_geojson_filename(_KAGAWA, FacilityKind.SAPA)
    real_write_geojson = write_geojson

    def _fail_only_kagawa(features, filename, output_dir=None, **kwargs):
        if filename == kagawa_filename:
            raise GeoJsonValidationError([ValidationIssue(location="features[0]", message="検証違反(意図的)")])
        return real_write_geojson(features, filename, output_dir=output_dir, **kwargs)

    monkeypatch.setattr("roadstop_scraper.sapa.runner.write_geojson", _fail_only_kagawa)

    resume_store = ResumeStore(state_dir=tmp_path / ".resume")
    resume_key = "sapa-test-prefecture-failure"
    resume = UrlResumeTracker(resume_key, store=resume_store)
    partial_store = SapaPartialStore(store=resume_store)

    result = run_scope(
        ScopeSpec(region="shikoku"),
        fetcher=fetcher,
        geocoder=_RunScopeFakeGeocoder(),
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_store,
    )

    assert result.failed_site_keys == frozenset()
    assert result.failed_prefecture_codes == frozenset({"37"})

    tokushima_filename = build_geojson_filename(_TOKUSHIMA, FacilityKind.SAPA)
    written = read_geojson(output_dir / tokushima_filename)
    assert [f.properties.name for f in written] == ["施設徳島"]
    assert not (output_dir / kagawa_filename).exists()

    # 1都道府県でも失敗が残るためresume/partial_storeはクリアされない。
    assert resume_store.load(resume_key) is not None


def test_confirmed_atの検証_省略時にtime_utility_nowが1回だけ呼ばれ全都道府県の出力へ同一のconfirmed_atが使われる(
    tmp_path, monkeypatch
):
    """``confirmed_at``省略時、``time_utility.now()``が本呼び出し全体で1回だけ
    取得され、その同一値が範囲内の全都道府県の出力(GeoJSON・index.json)へ
    一貫して使われることを検証する(1回の実行セッションとしての単一スナップ
    ショット、michinoeki.runner.run_scopeと同じ規律)。
    """
    output_dir = tmp_path / "geo-json"
    fixed_now = datetime(2026, 7, 20, 3, 0, 0, tzinfo=UTC)
    call_count = {"n": 0}

    def _fake_now() -> datetime:
        call_count["n"] += 1
        return fixed_now

    monkeypatch.setattr("roadstop_scraper.sapa.runner.time_utility.now", _fake_now)

    url_toku = "https://site-a.example/tokushima-1"
    url_kagawa = "https://site-a.example/kagawa-1"
    site_a = _RunScopeFakeSite(
        key="site-a",
        owned_prefix="https://site-a.example/",
        listing_kind="json",
        listing_url_list=("https://site-a.example/listing",),
        details_by_url={
            url_toku: _sapa_detail(
                name="施設徳島",
                address=f"{_TOKUSHIMA.name_ja}徳島市内町1-1",
                coordinate=Coordinate(longitude=134.5, latitude=34.1),
            ),
            url_kagawa: _sapa_detail(
                name="施設香川",
                address=f"{_KAGAWA.name_ja}高松市サンポート1-1",
                coordinate=Coordinate(longitude=134.0, latitude=34.3),
            ),
        },
    )
    fetcher = _RunScopeFakeFetcher(
        json_by_url={
            "https://site-a.example/listing": SapaListingResult(
                stubs=(
                    SapaStub(display_name="a", detail_url=url_toku),
                    SapaStub(display_name="b", detail_url=url_kagawa),
                ),
                listed_urls=frozenset({url_toku, url_kagawa}),
                skipped_count=0,
            ),
        }
    )
    monkeypatch.setattr("roadstop_scraper.sapa.runner.ALL_SITES", (site_a,))

    resume_store = ResumeStore(state_dir=tmp_path / ".resume")
    resume = UrlResumeTracker("sapa-test-confirmed-at", store=resume_store)
    partial_store = SapaPartialStore(store=resume_store)

    run_scope(
        ScopeSpec(region="shikoku"),
        fetcher=fetcher,
        geocoder=_RunScopeFakeGeocoder(),
        resume=resume,
        confirmed_at=None,
        output_dir=output_dir,
        partial_result_store=partial_store,
    )

    # confirmed_at省略時、本呼び出し全体でtime_utility.now()が1回だけ呼ばれる
    # (都道府県ごと・サイトごとの再取得は行わない)。
    assert call_count["n"] == 1

    tokushima_filename = build_geojson_filename(_TOKUSHIMA, FacilityKind.SAPA)
    kagawa_filename = build_geojson_filename(_KAGAWA, FacilityKind.SAPA)
    tokushima_written = read_geojson(output_dir / tokushima_filename)
    kagawa_written = read_geojson(output_dir / kagawa_filename)
    assert tokushima_written[0].properties.last_confirmed_at == fixed_now
    assert kagawa_written[0].properties.last_confirmed_at == fixed_now

    index = index_store.load_index(output_dir / "index.json")
    updated_at_by_path = {entry.path: entry.updated_at for entry in index.files}
    assert updated_at_by_path[tokushima_filename] == fixed_now
    assert updated_at_by_path[kagawa_filename] == fixed_now
