"""都道府県単位の収集ループと個別失敗のスキップ処理(runner._collect_stubs)の検証。

タスク5.1の観測可能な完了条件を検証する: 一部道の駅の詳細抽出が失敗しても
他の道の駅の処理が継続され、成功結果の蓄積件数とスキップ件数がそれぞれ正しく
確認できること、処理済み判定により重複処理が発生しないこと。
``tests/scraping/test_integration_fetch_to_extract.py``の偽セッション
(``_FakeResponse``/``_FakeSession``)パターンを踏襲し、実際の``PageFetcher``へ
偽セッションを注入する形で検証する(HTTP層のみをスタブ化し、fetch_text→
parse_html→extract_station_propertiesの一連の流れは実際のコンポーネントの
まま通す)。
"""

from __future__ import annotations

from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import Coordinate, FacilityFeature, find_prefecture
from roadstop_scraper.michinoeki.listing import StationStub
from roadstop_scraper.michinoeki.runner import _collect_stubs
from roadstop_scraper.scraping import PageFetcher, ScrapingConfig, UrlResumeTracker

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
