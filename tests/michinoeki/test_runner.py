"""都道府県単位のrunnerパイプライン(runner._collect_stubs/run_prefecture)の検証。

タスク5.1の観測可能な完了条件(``_collect_stubs``)に加え、タスク5.2の観測可能な
完了条件を検証する: 1都道府県分の一覧取得から出力・管理ファイル更新までが
一貫して動作すること、出力前検証違反時にファイルが書き込まれず当該都道府県のみが
中断されること、一覧取得失敗時も同様に当該都道府県のみが中断されファイルが
書き込まれないこと。さらにタスク5.3の観測可能な完了条件を検証する: 都道府県
処理の途中を模した中断の後に再実行した場合、中断前に成功していた収集結果と
スキップ件数が失われずに最終出力へ反映されること、出力成功後は``_PartialResultStore``
の保持内容が消去され次回実行に影響しないこと(出力前検証違反時に消去されない
ことも併せて検証する)。``tests/scraping/test_integration_fetch_to_extract.py``の
偽セッション(``_FakeResponse``/``_FakeSession``)パターンを踏襲し、実際の
``PageFetcher``へ偽セッションを注入する形で検証する(HTTP層のみをスタブ化し、
fetch_text→parse_html→extract_station_propertiesの一連の流れは実際の
コンポーネントのまま通す)。一覧ページのフィクスチャHTML構造は
``tests/michinoeki/test_listing.py``を参考にしている。
"""

from __future__ import annotations

from datetime import UTC, datetime

from roadstop_scraper.common import index_store
from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import (
    Coordinate,
    FacilityFeature,
    FacilityKind,
    FacilityStatus,
    GeoJsonValidationError,
    ValidationIssue,
    build_geojson_filename,
    find_prefecture,
    read_geojson,
)
from roadstop_scraper.michinoeki.detail import extract_station_properties
from roadstop_scraper.michinoeki.listing import StationStub
from roadstop_scraper.michinoeki.runner import PrefectureRunResult, _collect_stubs, _PartialResultStore, run_prefecture
from roadstop_scraper.michinoeki.site_urls import build_search_url
from roadstop_scraper.scraping import PageFetcher, ScrapingConfig, UrlResumeTracker, parse_html

_CONFIRMED_AT = datetime(2026, 7, 18, 9, 0, 0, tzinfo=UTC)

_SUCCESS_HTML_TEMPLATE = """
<html>
  <body>
    <div class="info">
      <dl><dt>道の駅名</dt><dd>{name}</dd></dl>
      <dl><dt>所在地</dt><dd>068-2165 北海道三笠市岡山1056-1</dd></dl>
      <dl><dt>TEL</dt><dd>01267-2-3999</dd></dl>
    </div>
    <div class="viewFacility">
      <ul></ul>
    </div>
  </body>
</html>
"""

# 名称ddが空文字のため、extract_station_propertiesがStructureChangedErrorを
# 送出する(構造変化を誘発する不正HTML)。
_STRUCTURE_CHANGED_HTML = """
<html>
  <body>
    <div class="info">
      <dl><dt>道の駅名</dt><dd></dd></dl>
      <dl><dt>所在地</dt><dd>068-2165 北海道三笠市岡山1056-1</dd></dl>
    </div>
    <div class="viewFacility">
      <ul></ul>
    </div>
  </body>
</html>
"""

# 一覧/検索ページのjs-data-box構造を模したフィクスチャHTML
# (tests/michinoeki/test_listing.pyのフィクスチャと同じ形)。
_LISTING_HTML_NO_ELEMENTS = """
<html>
  <body>
    <main>
      <p>該当する道の駅はありません</p>
    </main>
  </body>
</html>
"""


def _listing_html(entries: list[tuple[str, str, float, float]]) -> str:
    """(name, link, lat, lng)のリストからjs-data-box要素群を持つ一覧HTMLを生成する。"""
    boxes = "\n".join(
        f'<div class="js-data-box" data-name="{name}" data-link="{link}" data-lat="{lat}" data-lng="{lng}"></div>'
        for name, link, lat, lng in entries
    )
    return f"""
<html>
  <body>
    <main>
      {boxes}
    </main>
  </body>
</html>
"""


class _FakeResponse:
    """``ResponseLike``を満たす偽レスポンス(test_integration_fetch_to_extract.pyと同じ形)。"""

    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.apparent_encoding = "utf-8"


class _FakeSession:
    """URLに応じて異なる応答を返す偽セッション。HTTP層のみをスタブ化する。"""

    def __init__(self, responses_by_url: dict[str, str]) -> None:
        self._responses_by_url = responses_by_url
        self.calls: list[str] = []

    def get(self, url, *, timeout, headers):
        self.calls.append(url)
        html = self._responses_by_url[url]
        return _FakeResponse(
            200,
            html.encode("utf-8"),
            headers={"Content-Type": "text/html; charset=utf-8"},
        )


def _fast_config() -> ScrapingConfig:
    return ScrapingConfig(
        timeout_seconds=5.0,
        max_retries=0,
        retry_wait_seconds=0.0,
        min_request_interval_seconds=0.0,
    )


def _make_fetcher(responses_by_url: dict[str, str]) -> tuple[PageFetcher, _FakeSession]:
    session = _FakeSession(responses_by_url)
    fetcher = PageFetcher(_fast_config(), session=session)
    return fetcher, session


def _make_resume(tmp_path) -> UrlResumeTracker:
    return UrlResumeTracker("michinoeki-test", store=ResumeStore(state_dir=tmp_path / ".resume"))


def test_収集ループの検証_一部の詳細抽出が失敗しても他の道の駅の処理が継続され成功結果とスキップ件数が正しく蓄積される(
    tmp_path,
):
    prefecture = find_prefecture("01")
    stub_ok1 = StationStub(
        name="道の駅A",
        detail_url="https://example.com/stations/1",
        coordinate=Coordinate(longitude=141.0, latitude=43.0),
    )
    stub_fail = StationStub(
        name="道の駅B",
        detail_url="https://example.com/stations/2",
        coordinate=Coordinate(longitude=141.1, latitude=43.1),
    )
    stub_ok2 = StationStub(
        name="道の駅C",
        detail_url="https://example.com/stations/3",
        coordinate=Coordinate(longitude=141.2, latitude=43.2),
    )
    responses = {
        stub_ok1.detail_url: _SUCCESS_HTML_TEMPLATE.format(name="道の駅A"),
        stub_fail.detail_url: _STRUCTURE_CHANGED_HTML,
        stub_ok2.detail_url: _SUCCESS_HTML_TEMPLATE.format(name="道の駅C"),
    }
    fetcher, session = _make_fetcher(responses)
    resume = _make_resume(tmp_path)

    features, skipped_count = _collect_stubs(
        [stub_ok1, stub_fail, stub_ok2],
        prefecture,
        fetcher=fetcher,
        resume=resume,
    )

    # 失敗した1件を挟んでも他の2件の処理が継続され、成功結果として蓄積される。
    assert len(features) == 2
    assert skipped_count == 1
    assert session.calls == [stub_ok1.detail_url, stub_fail.detail_url, stub_ok2.detail_url]

    # 戻り値のFacilityFeatureがstub.coordinateと抽出されたFacilityPropertiesを
    # 正しく組み合わせたものであることを確認する。
    feature_1 = next(f for f in features if f.properties.source_url == stub_ok1.detail_url)
    assert isinstance(feature_1, FacilityFeature)
    assert feature_1.coordinate == stub_ok1.coordinate
    assert feature_1.properties.name == "道の駅A"

    feature_3 = next(f for f in features if f.properties.source_url == stub_ok2.detail_url)
    assert feature_3.coordinate == stub_ok2.coordinate
    assert feature_3.properties.name == "道の駅C"


def test_収集ループの検証_成功も失敗もmark_processedが呼ばれ次回はresumeで処理済みと判定される(tmp_path):
    prefecture = find_prefecture("01")
    stub_ok = StationStub(
        name="道の駅A",
        detail_url="https://example.com/stations/1",
        coordinate=Coordinate(longitude=141.0, latitude=43.0),
    )
    stub_fail = StationStub(
        name="道の駅B",
        detail_url="https://example.com/stations/2",
        coordinate=Coordinate(longitude=141.1, latitude=43.1),
    )
    responses = {
        stub_ok.detail_url: _SUCCESS_HTML_TEMPLATE.format(name="道の駅A"),
        stub_fail.detail_url: _STRUCTURE_CHANGED_HTML,
    }
    fetcher, _session = _make_fetcher(responses)
    resume = _make_resume(tmp_path)

    assert resume.is_processed(stub_ok.detail_url) is False
    assert resume.is_processed(stub_fail.detail_url) is False

    _collect_stubs([stub_ok, stub_fail], prefecture, fetcher=fetcher, resume=resume)

    # 4.1-4.3: 成功時だけでなく失敗時もmark_processedが呼ばれ、次回は
    # 処理済みと判定される(同一の中断・再開サイクル内での無駄な再試行を防ぐ)。
    assert resume.is_processed(stub_ok.detail_url) is True
    assert resume.is_processed(stub_fail.detail_url) is True


def test_収集ループの検証_既に処理済みのstationstubは詳細ページの取得すら行われない(tmp_path):
    prefecture = find_prefecture("01")
    stub_already_processed = StationStub(
        name="道の駅A",
        detail_url="https://example.com/stations/1",
        coordinate=Coordinate(longitude=141.0, latitude=43.0),
    )
    stub_new = StationStub(
        name="道の駅B",
        detail_url="https://example.com/stations/2",
        coordinate=Coordinate(longitude=141.1, latitude=43.1),
    )
    # stub_already_processedの応答は登録しない: 取得が発生した場合はKeyErrorで
    # テストが失敗し、「詳細ページの取得が行われないこと」を検出できる。
    responses = {
        stub_new.detail_url: _SUCCESS_HTML_TEMPLATE.format(name="道の駅B"),
    }
    fetcher, session = _make_fetcher(responses)
    resume = _make_resume(tmp_path)
    resume.mark_processed(stub_already_processed.detail_url)

    features, skipped_count = _collect_stubs(
        [stub_already_processed, stub_new],
        prefecture,
        fetcher=fetcher,
        resume=resume,
    )

    # 6.1: 重複処理の防止。処理済みURLへのリクエストは一切発生しない。
    assert session.calls == [stub_new.detail_url]
    # 既に処理済みのStationStubは成功結果・スキップ件数のいずれにも計上しない。
    assert len(features) == 1
    assert features[0].properties.source_url == stub_new.detail_url
    assert skipped_count == 0


def test_run_prefectureの検証_1都道府県分の一覧取得から出力とindex更新までが一貫して動作する(tmp_path):
    prefecture = find_prefecture("01")
    listing_url = build_search_url(prefecture)
    detail_url_a = "https://example.com/stations/1"
    detail_url_b = "https://example.com/stations/2"
    responses = {
        listing_url: _listing_html(
            [
                ("道の駅A", detail_url_a, 43.0, 141.0),
                ("道の駅B", detail_url_b, 43.1, 141.1),
            ]
        ),
        detail_url_a: _SUCCESS_HTML_TEMPLATE.format(name="道の駅A"),
        detail_url_b: _SUCCESS_HTML_TEMPLATE.format(name="道の駅B"),
    }
    fetcher, session = _make_fetcher(responses)
    resume = _make_resume(tmp_path)
    partial_result_store = _make_partial_result_store(tmp_path)
    output_dir = tmp_path / "geo-json"

    result = run_prefecture(
        prefecture,
        fetcher=fetcher,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_result_store,
    )

    # 一覧ページ・両詳細ページの取得が発生し、一貫してパイプラインが完走する。
    assert session.calls == [listing_url, detail_url_a, detail_url_b]
    assert isinstance(result, PrefectureRunResult)
    assert result.prefecture == prefecture
    assert result.scraped_count == 2
    assert result.skipped_count == 0
    assert result.reactivated_count == 0
    assert result.newly_deleted_count == 0
    assert result.purged_count == 0

    filename = build_geojson_filename(prefecture, FacilityKind.MICHINOEKI)
    output_path = output_dir / filename
    assert output_path.exists()

    written_features = read_geojson(output_path)
    assert len(written_features) == 2
    names = {feature.properties.name for feature in written_features}
    assert names == {"道の駅A", "道の駅B"}
    for feature in written_features:
        assert feature.properties.status is FacilityStatus.ACTIVE
        assert feature.properties.last_confirmed_at == _CONFIRMED_AT

    index = index_store.load_index(output_dir / "index.json")
    assert len(index.files) == 1
    assert index.files[0].path == filename
    assert index.files[0].updated_at == _CONFIRMED_AT


def test_run_prefectureの検証_出力前検証違反時にファイルが書き込まれず当該都道府県のみが中断される(
    tmp_path, monkeypatch
):
    prefecture = find_prefecture("01")
    listing_url = build_search_url(prefecture)
    detail_url_a = "https://example.com/stations/1"
    responses = {
        listing_url: _listing_html([("道の駅A", detail_url_a, 43.0, 141.0)]),
        detail_url_a: _SUCCESS_HTML_TEMPLATE.format(name="道の駅A"),
    }
    fetcher, _session = _make_fetcher(responses)
    resume = _make_resume(tmp_path)
    partial_result_store = _make_partial_result_store(tmp_path)
    output_dir = tmp_path / "geo-json"

    def _raise_validation_error(*_args, **_kwargs):
        raise GeoJsonValidationError([ValidationIssue(location="features[0]", message="検証違反(意図的)")])

    # write_geojsonが出力前検証違反を送出する状況をモンキーパッチで再現する
    # (5.2: 出力前検証違反時にファイルが書き込まれないことを検証するため)。
    monkeypatch.setattr("roadstop_scraper.michinoeki.runner.write_geojson", _raise_validation_error)

    result = run_prefecture(
        prefecture,
        fetcher=fetcher,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_result_store,
    )

    # 当該都道府県の処理のみが中断され、Noneが返る。
    assert result is None

    filename = build_geojson_filename(prefecture, FacilityKind.MICHINOEKI)
    # write_geojson自体が検証違反時にファイルを書き込まない実装であり、
    # 本テストではモンキーパッチによりその経路自体が実行されないため、
    # 出力ファイル・index.jsonのいずれも作成されない。
    assert not (output_dir / filename).exists()
    assert not (output_dir / "index.json").exists()


def test_run_prefectureの検証_一覧取得失敗時にNoneが返りファイルが書き込まれない(tmp_path):
    prefecture = find_prefecture("02")
    listing_url = build_search_url(prefecture)
    responses = {listing_url: _LISTING_HTML_NO_ELEMENTS}
    fetcher, session = _make_fetcher(responses)
    resume = _make_resume(tmp_path)
    partial_result_store = _make_partial_result_store(tmp_path)
    output_dir = tmp_path / "geo-json"

    result = run_prefecture(
        prefecture,
        fetcher=fetcher,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_result_store,
    )

    # 2.3, 5.2: 一覧取得失敗時はNoneが返り、当該都道府県のみ中断される。
    # 詳細ページへのリクエストは一切発生しない。
    assert result is None
    assert session.calls == [listing_url]

    filename = build_geojson_filename(prefecture, FacilityKind.MICHINOEKI)
    assert not (output_dir / filename).exists()
    assert not (output_dir / "index.json").exists()


def _make_partial_result_store(tmp_path) -> ResumeStore:
    return ResumeStore(state_dir=tmp_path / ".resume-partial")


def test_run_prefectureの検証_中断後の再実行で中断前の成功結果とスキップ件数が最終出力へ反映される(tmp_path):
    """5.3: 都道府県処理の途中(_PartialResultStoreへの永続化後・write_geojson到達前)を
    模して中断し再実行した場合、中断前に抽出成功していた道の駅・スキップ件数が
    失われずに最終出力へ反映されることを検証する(design.md Testing Strategy)。

    復元分(1件目成功・2件目失敗)に加え、今回の``run_prefecture``呼び出し自体の
    最中に新規(復元ではない)の成功(3件目)・失敗(4件目)がともに発生する
    ケースを含める。これにより、``_collect_stubs``内で新たに発生した失敗が
    ``partial_store.add_skip()``で確定するたびに逐次永続化・合算される経路
    (復元済みスキップの単純な引き継ぎだけでは検証できない経路)を確認する。
    """
    prefecture = find_prefecture("01")
    listing_url = build_search_url(prefecture)
    detail_url_a = "https://example.com/stations/1"
    detail_url_b = "https://example.com/stations/2"
    detail_url_c = "https://example.com/stations/3"
    detail_url_d = "https://example.com/stations/4"
    responses = {
        listing_url: _listing_html(
            [
                ("道の駅A", detail_url_a, 43.0, 141.0),
                ("道の駅B", detail_url_b, 43.1, 141.1),
                ("道の駅C", detail_url_c, 43.2, 141.2),
                ("道の駅D", detail_url_d, 43.3, 141.3),
            ]
        ),
        detail_url_a: _SUCCESS_HTML_TEMPLATE.format(name="道の駅A"),
        detail_url_b: _STRUCTURE_CHANGED_HTML,
        detail_url_c: _SUCCESS_HTML_TEMPLATE.format(name="道の駅C"),
        detail_url_d: _STRUCTURE_CHANGED_HTML,
    }
    fetcher, session = _make_fetcher(responses)
    resume = _make_resume(tmp_path)
    partial_result_store = _make_partial_result_store(tmp_path)
    output_dir = tmp_path / "geo-json"

    # 中断前の状態を再現する: 1件目は成功・2件目は失敗として既にresumeと
    # PartialResultStoreの双方に永続化済みという状況を、実際のrun_prefectureとは
    # 別の使い捨てフェッチャーで組み立てる(再実行時のsession.callsへ紛れ込ませないため)。
    # 3件目・4件目は今回のrun_prefecture呼び出しの最中に初めて処理される
    # (3件目は新規成功・4件目は新規失敗)。
    prep_fetcher, _prep_session = _make_fetcher(responses)
    fetched_a = prep_fetcher.fetch_text(detail_url_a)
    page_a = parse_html(fetched_a.text, fetched_a.url)
    properties_a = extract_station_properties(page_a, prefecture, detail_url_a)
    feature_a = FacilityFeature(
        coordinate=Coordinate(longitude=141.0, latitude=43.0),
        properties=properties_a,
    )

    pre_partial = _PartialResultStore(prefecture, store=partial_result_store)
    pre_partial.add_feature(feature_a)
    pre_partial.add_skip()

    resume.mark_processed(detail_url_a)
    resume.mark_processed(detail_url_b)

    result = run_prefecture(
        prefecture,
        fetcher=fetcher,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_result_store,
    )

    # 1件目・2件目はresumeで処理済みのため詳細ページの再取得は発生せず、
    # 3件目・4件目のみが新規に処理される。
    assert session.calls == [listing_url, detail_url_c, detail_url_d]
    assert isinstance(result, PrefectureRunResult)
    # 6.1-6.3, 4.3: 中断前(1件成功・1件失敗)と今回新規分(1件成功・1件失敗)の
    # 成功結果・スキップ件数が合算される。
    assert result.scraped_count == 2
    assert result.skipped_count == 2

    filename = build_geojson_filename(prefecture, FacilityKind.MICHINOEKI)
    written_features = read_geojson(output_dir / filename)
    names = {feature.properties.name for feature in written_features}
    # 中断前に成功していた1件目・今回新規に成功した3件目の両方が出力に含まれる。
    assert names == {"道の駅A", "道の駅C"}

    # 5.3: 出力まで正常完了したため、部分結果キャッシュは消去され次回実行に影響しない。
    assert partial_result_store.load(f"michinoeki-partial-{prefecture.code}") is None


def test_run_prefectureの検証_出力前検証違反時に部分結果キャッシュが消去されず次回再開できる(tmp_path, monkeypatch):
    """design.md Implementation Notes: GeoJsonValidationError発生時は_PartialResultStoreを
    消去しない(次回同じ部分結果から再開できるようにするため)。

    ``write_geojson``は``_collect_stubs``完了後に呼ばれるため、モンキーパッチで
    ここを失敗させても、それより前の収集ループで確定した結果(1件の新規成功・
    1件の新規失敗)はすでに``_PartialResultStore``へ永続化済みのはずである。
    この永続化は``run_prefecture``の戻り値(``PrefectureRunResult.skipped_count``)
    ではなく、同じ``store``から独立して再構築した``_PartialResultStore``を直接
    読み戻すことで検証する。こうすることで、収集ループ内の
    ``partial_store.add_skip()``呼び出し自体が実際に永続化を行っていることを、
    戻り値経由の間接的な確認に頼らず確かめられる(戻り値のskipped_countは
    ``_collect_stubs``のローカル戻り値からも独立に算出できてしまうため)。
    """
    prefecture = find_prefecture("01")
    listing_url = build_search_url(prefecture)
    detail_url_a = "https://example.com/stations/1"
    detail_url_b = "https://example.com/stations/2"
    responses = {
        listing_url: _listing_html(
            [
                ("道の駅A", detail_url_a, 43.0, 141.0),
                ("道の駅B", detail_url_b, 43.1, 141.1),
            ]
        ),
        detail_url_a: _SUCCESS_HTML_TEMPLATE.format(name="道の駅A"),
        detail_url_b: _STRUCTURE_CHANGED_HTML,
    }
    fetcher, _session = _make_fetcher(responses)
    resume = _make_resume(tmp_path)
    partial_result_store = _make_partial_result_store(tmp_path)
    output_dir = tmp_path / "geo-json"

    def _raise_validation_error(*_args, **_kwargs):
        raise GeoJsonValidationError([ValidationIssue(location="features[0]", message="検証違反(意図的)")])

    monkeypatch.setattr("roadstop_scraper.michinoeki.runner.write_geojson", _raise_validation_error)

    result = run_prefecture(
        prefecture,
        fetcher=fetcher,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_result_store,
    )

    assert result is None

    restored = _PartialResultStore(prefecture, store=partial_result_store)
    assert [f.properties.name for f in restored.features] == ["道の駅A"]
    # 2件目の新規失敗(復元分ではなく今回の収集ループ中に初めて発生したもの)が
    # partial_store.add_skip()によって永続化されていることを直接検証する。
    assert restored.skipped_count == 1
