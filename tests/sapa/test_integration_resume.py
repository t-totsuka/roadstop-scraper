"""レジューム(中断・再開)の結合検証(タスク6.2)。

``tests/sapa/test_collector.py``(タスク4.2)には既に「レジューム済みURLは
詳細取得を行わずスキップする」検証があるが、``_FakeSite``越しの単発
``collect_site``呼び出しのみを対象とし、実サイトアダプタ経由・2回目の
呼び出しでの実際の再取得ゼロ件は検証していない。``tests/sapa/test_runner.py``
(タスク5.2)には「全サイト・全都道府県成功時のみ``resume.clear()``/
``partial_store.clear()``が呼ばれる(その逆も)」検証があるが、``_RunScopeFakeSite``
越しであり、かつ検証は``resume_store.load(key)``や``SapaPartialStore``の
再構築(インメモリAPI経由)に留まり、``ResumeStore``の状態ディレクトリ上の
実ファイルが本当に削除される/残ることまでは確認していない。

本ファイルはこれらのギャップを埋める、実際の``EastSite``(``tests/sapa/
test_integration_deletion.py``がタスク6.1で確立した「偽セッションを実際の
``PageFetcher``へ注入し、``parse_listing``/``extract_detail``は実装のまま
通す」技法を踏襲)を用いた3つの結合検証を行う(design.md「Testing Strategy」
Integration Testsのレジューム項、Requirements 7.1-7.3)。

タスク6.1との境界(``_Boundary:_``より): 本ファイルは6.1
(``test_integration_deletion.py``)とファイル・フィクスチャを一切共有しない。
偽セッション・偽レスポンス・偽ジオコーダー・一覧/詳細HTML生成関数は、
同種のプロトコル(``SessionLike``)を満たす必要上、構造は類似するが本ファイル
専用に独立して定義する(6.1のクラス・関数は一切importしない)。

「中断・再開」のシミュレーション技法: ``tests/michinoeki/test_runner.py``の
確立した技法(``_PartialResultStore``/``UrlResumeTracker``へ直接
``add_feature``/``mark_processed``を呼んで「前回途中まで進んで永続化済み」の
状態を事前構築し、1回の実呼び出しで再開を検証する)を調査した。本ファイルの
7.2検証(中断直後の状態と再開後の最終結果の両方を検証したい)には、実際に
``collect_site``を実行中に強制終了させる技法の方がより直接的であるため、
``ScrapingEngineError``のいかなるサブクラスでもない検証専用の例外
(``_SimulatedProcessCrash``)を偽セッションから送出させ、``collect_site``の
``except ScrapingEngineError``節を素通りして呼び出し元まで伝播させる。
実装確認済み: ``scraping.fetcher.PageFetcher._send_with_retry``の
``except``節は``requests.exceptions.RequestException``系のみを対象とし、
それ以外の例外(本テストの``_SimulatedProcessCrash``を含む)は無変換で
呼び出し元へ伝播する。1施設(A)の処理(詳細取得→結果永続化→
``mark_processed``)が完了した直後に次の施設(C)でこの例外を発生させることで、
「Aは永続化済み・Cは未処理」という中断直後の状態を、実際に``collect_site``を
中断させて作り出す(pre-seed方式ではなく実クラッシュ方式)。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import Coordinate, find_prefecture
from roadstop_scraper.pipeline import ScopeSpec
from roadstop_scraper.sapa.collector import SapaPartialStore, collect_site
from roadstop_scraper.sapa.runner import SapaScopeRunResult, run_scope
from roadstop_scraper.sapa.sites import EastSite
from roadstop_scraper.scraping import PageFetcher, ScrapingConfig, UrlResumeTracker

_CONFIRMED_AT = datetime(2026, 7, 19, 9, 0, 0, tzinfo=UTC)

_TOKYO = find_prefecture("13")
_NAGANO = find_prefecture("20")

# 東日本(driveplaza.com)のarealist別一覧URL(east.py._LISTING_URL_TEMPLATEと
# 同じ構成。実装を直接importせず、実サイトのURL構成を模したフィクスチャとして
# 独立に構成する。tests/sapa/test_integration_deletion.pyと同じ値になるのは
# サイト側のURL構成そのものが同一のためであり、フィクスチャの共有ではない)。
_EAST_TOKYO_LISTING_URL = "https://www.driveplaza.com/dp/SAPAServRes?arealist=3&HIGHWAY=AA"
_EAST_NAGANO_LISTING_URL = "https://www.driveplaza.com/dp/SAPAServRes?arealist=4&HIGHWAY=AA"
_CENTRAL_SEARCH_URL = "https://sapa.c-nexco.co.jp/search/result"


class _SimulatedProcessCrash(Exception):
    """検証専用の「プロセスが強制終了した」ことを模す例外。

    ``scraping.errors.ScrapingEngineError``のいかなるサブクラスでもないため、
    ``sapa.collector.collect_site``内の``except ScrapingEngineError``には
    一切捕捉されず、呼び出し元まで素通しされる。
    """


class _StubResponse:
    """``ResponseLike``を満たす最小限の偽レスポンス。"""

    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.apparent_encoding = "utf-8"


class _StubSession:
    """URLごとに登録済みのHTML・強制例外・失敗ステータスを返す偽セッション。

    ``forbidden_urls``に含まれるURLが取得された場合は即座に``AssertionError``
    を送出する(7.1: レジューム済みURLへの再取得が実際に発生しないことを、
    ``collect_site``の分岐ロジックに頼らず、HTTP層の監視としても二重に保証
    する)。``raise_by_url``に登録した例外はそのまま送出する(7.2: プロセス
    強制終了の模擬)。``failure_status_by_url``は一覧取得失敗(2.3)の模擬に使う。
    """

    def __init__(
        self,
        html_by_url: dict[str, str],
        *,
        raise_by_url: dict[str, Exception] | None = None,
        failure_status_by_url: dict[str, int] | None = None,
        forbidden_urls: frozenset[str] = frozenset(),
    ) -> None:
        self._html_by_url = html_by_url
        self._raise_by_url = raise_by_url or {}
        self._failure_status_by_url = failure_status_by_url or {}
        self._forbidden_urls = forbidden_urls
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> _StubResponse:
        if url in self._forbidden_urls:
            raise AssertionError(f"処理済みのはずのURLへ再取得が発生した: {url}")
        self.calls.append(url)
        if url in self._raise_by_url:
            raise self._raise_by_url[url]
        if url in self._failure_status_by_url:
            return _StubResponse(self._failure_status_by_url[url], b"")
        return _StubResponse(200, self._html_by_url[url].encode("utf-8"))


class _StubGeocoder:
    """住所によらず固定の座標を返す偽ジオコーダー。

    ``EastSite.extract_detail``は常に``coordinate=None``を返す実装のため、
    本ファイルの全施設がジオコーディング(4.2)経由となる。本テストの主眼は
    座標補完自体ではなくレジューム(7.1-7.3)のため、固定座標を返す最小限の
    偽物で足りる。
    """

    def __init__(self, result: Coordinate) -> None:
        self._result = result
        self.calls: list[str] = []

    def geocode(self, address: str) -> Coordinate | None:
        self.calls.append(address)
        return self._result


def _fast_config() -> ScrapingConfig:
    return ScrapingConfig(
        timeout_seconds=5.0,
        max_retries=0,
        retry_wait_seconds=0.0,
        min_request_interval_seconds=0.0,
    )


def _listing_html(entries: list[tuple[str, str]]) -> str:
    """(表示名, 詳細URL)列から``div.box-sapa``要素群を持つ一覧HTMLを生成する(east.pyの実測構造)。"""
    boxes = "\n".join(
        f'<div class="box-sapa"><h3 class="ttl-sapaName"><a href="{href}">{name}</a></h3></div>'
        for name, href in entries
    )
    return f"<html><body><main>{boxes}</main></body></html>"


def _detail_html(*, name: str, road_name: str, address: str) -> str:
    """east.pyのテンプレートA構造を模した最小限の詳細ページHTML。"""
    return f"""
<html>
  <body>
    <span class="txt-way">{road_name}</span>
    <h1 class="c-titleH1"><span class="txt-title">{name}</span></h1>
    <div class="box-facility">
      <div class="box-info"><p>{address}</p></div>
    </div>
  </body>
</html>
"""


def _make_state(tmp_path, key: str) -> tuple[UrlResumeTracker, SapaPartialStore, ResumeStore]:
    store = ResumeStore(state_dir=tmp_path / ".resume")
    return UrlResumeTracker(key, store=store), SapaPartialStore(store=store), store


# ---------------------------------------------------------------------------
# 7.1: レジューム済みURLの再取得スキップ(実サイトアダプタ・2回目呼び出し経由)。
# ---------------------------------------------------------------------------


def test_collect_siteの検証_処理済み施設の場合_同じ状態ディレクトリでの再実行時に詳細取得を一切行わない(tmp_path):
    """tests/sapa/test_collector.pyの同種テスト(タスク4.2)は``_FakeSite``越しの
    単発``collect_site``呼び出しのみを検証しており、実サイトアダプタ
    (``EastSite``)経由・「1回目で処理済み記録→2回目の(新規インスタンスでの)
    呼び出しで実際に再取得ゼロ件」という結合経路は未検証だった(本タスクの
    監査対象のギャップ)。
    """
    url_a = "https://www.driveplaza.com/sapa/1010/1010001/1/"
    url_b = "https://www.driveplaza.com/sapa/1010/1010002/1/"
    html_by_url = {
        _EAST_TOKYO_LISTING_URL: _listing_html([("テスト東京SA-A(上り)", url_a), ("テスト東京SA-B(上り)", url_b)]),
        url_a: _detail_html(name="テスト東京SA-A", road_name="中央自動車道", address="東京都新宿区西新宿2-8-1"),
        url_b: _detail_html(name="テスト東京SA-B", road_name="中央自動車道", address="東京都新宿区西新宿2-8-2"),
    }
    state_key = "sapa-test-resume-skip"
    resume_1, partial_store_1, _store = _make_state(tmp_path, state_key)

    session_1 = _StubSession(html_by_url)
    fetcher_1 = PageFetcher(_fast_config(), session=session_1)
    geocoder_1 = _StubGeocoder(Coordinate(longitude=139.69, latitude=35.69))

    first_result = collect_site(
        EastSite(), [_TOKYO], fetcher=fetcher_1, geocoder=geocoder_1, resume=resume_1, partial_store=partial_store_1
    )

    assert session_1.calls == [_EAST_TOKYO_LISTING_URL, url_a, url_b]
    assert len(first_result.features) == 2
    assert resume_1.is_processed(url_a) is True
    assert resume_1.is_processed(url_b) is True

    # 2回目: 同じ状態ディレクトリから新規構築した(1回目とは別インスタンスの)
    # UrlResumeTracker/SapaPartialStoreを使い、A・Bいずれのdetail_urlが
    # 取得されても即座に失敗するセッションで再実行する(再開シナリオ)。
    resume_2, partial_store_2, _store_2 = _make_state(tmp_path, state_key)
    session_2 = _StubSession(
        {_EAST_TOKYO_LISTING_URL: html_by_url[_EAST_TOKYO_LISTING_URL]},
        forbidden_urls=frozenset({url_a, url_b}),
    )
    fetcher_2 = PageFetcher(_fast_config(), session=session_2)
    geocoder_2 = _StubGeocoder(Coordinate(longitude=999.0, latitude=999.0))

    second_result = collect_site(
        EastSite(), [_TOKYO], fetcher=fetcher_2, geocoder=geocoder_2, resume=resume_2, partial_store=partial_store_2
    )

    # 一覧の再取得は発生する(新しい実行が一覧から始まるのは自然な挙動)が、
    # 処理済みのA・Bはdetail_urlへのfetch_textが一切発生しない
    # (forbidden_urlsのAssertionErrorが送出されずcalls==[一覧URLのみ]である
    # ことをもって、resume.is_processedによる事前スキップを実際に確認する)。
    assert session_2.calls == [_EAST_TOKYO_LISTING_URL]
    assert second_result.features == ()
    assert second_result.skipped_counts == {}


# ---------------------------------------------------------------------------
# 7.2: 処理途中の強制中断からの再開で結果が失われないこと。
# ---------------------------------------------------------------------------


def test_collect_siteの検証_詳細取得中に例外で処理が中断した場合_再開後に中断前の結果を保持しつつ残りの施設を処理する(
    tmp_path,
):
    """施設Aの処理(詳細取得→結果永続化→処理済み記録)が完了した直後、施設Cの
    詳細取得で``ScrapingEngineError``ではない例外(``_SimulatedProcessCrash``、
    プロセス強制終了の模擬)が発生し``collect_site``の外まで伝播する状況を作る。
    この例外を呼び出し側で捕捉した後(プロセス再起動を模す)、同じ状態
    ディレクトリから新規構築した``UrlResumeTracker``/``SapaPartialStore``・
    新しい``PageFetcher``/``GsiGeocoder``相当で``collect_site``を再実行し、
    Aが再取得されずCのみが処理されること、最終的にA・C両方が部分結果に含まれ
    取りこぼしがないことを検証する(design.md「結果保存が先、mark_processedは
    後」の順序規律により、Aの結果・処理済み記録は例外発生時点で既にディスクへ
    永続化されているはず)。
    """
    url_a = "https://www.driveplaza.com/sapa/1010/2010001/1/"
    url_c = "https://www.driveplaza.com/sapa/1010/2010002/1/"
    listing_html = _listing_html([("テスト東京SA-A(上り)", url_a), ("テスト東京SA-C(上り)", url_c)])
    detail_html_a = _detail_html(name="テスト東京SA-A", road_name="中央自動車道", address="東京都新宿区西新宿2-8-1")
    detail_html_c = _detail_html(name="テスト東京SA-C", road_name="中央自動車道", address="東京都新宿区西新宿2-8-3")

    state_key = "sapa-test-resume-crash"
    resume_1, partial_store_1, store = _make_state(tmp_path, state_key)

    session_1 = _StubSession(
        {_EAST_TOKYO_LISTING_URL: listing_html, url_a: detail_html_a},
        raise_by_url={url_c: _SimulatedProcessCrash("疑似クラッシュ")},
    )
    fetcher_1 = PageFetcher(_fast_config(), session=session_1)
    geocoder_1 = _StubGeocoder(Coordinate(longitude=139.69, latitude=35.69))

    with pytest.raises(_SimulatedProcessCrash):
        collect_site(
            EastSite(),
            [_TOKYO],
            fetcher=fetcher_1,
            geocoder=geocoder_1,
            resume=resume_1,
            partial_store=partial_store_1,
        )

    # 中断直後の状態(同じディレクトリから独立に再構築して実際の永続化を確認):
    # Aは処理済み・結果保存済み、Cは未処理。
    resume_after_crash = UrlResumeTracker(state_key, store=store)
    partial_after_crash = SapaPartialStore(store=store)
    assert resume_after_crash.is_processed(url_a) is True
    assert resume_after_crash.is_processed(url_c) is False
    assert {f.properties.source_url for f in partial_after_crash.features} == {url_a}

    # 再開(プロセス再起動を模す): 新しいfetcher/geocoder、同じ状態ディレクトリ
    # から再構築したresume/partial_store。Aのdetail_urlが再取得されたら即座に
    # 失敗するセッションを使う。
    resume_2 = UrlResumeTracker(state_key, store=store)
    partial_store_2 = SapaPartialStore(store=store)
    session_2 = _StubSession(
        {_EAST_TOKYO_LISTING_URL: listing_html, url_c: detail_html_c},
        forbidden_urls=frozenset({url_a}),
    )
    fetcher_2 = PageFetcher(_fast_config(), session=session_2)
    geocoder_2 = _StubGeocoder(Coordinate(longitude=139.60, latitude=35.60))

    second_result = collect_site(
        EastSite(), [_TOKYO], fetcher=fetcher_2, geocoder=geocoder_2, resume=resume_2, partial_store=partial_store_2
    )

    assert session_2.calls == [_EAST_TOKYO_LISTING_URL, url_c]
    assert {f.properties.source_url for f in second_result.features} == {url_c}

    # 最終的な部分結果(中断前のA + 今回のC)に欠落がない。
    final_partial = SapaPartialStore(store=store)
    assert {f.properties.source_url for f in final_partial.features} == {url_a, url_c}


# ---------------------------------------------------------------------------
# 7.3: 全成功時のみレジューム状態が実際にディスクから消え、失敗が残る場合は
# 残ること。
# ---------------------------------------------------------------------------


def test_run_scopeの検証_全サイト全都道府県成功の場合_レジューム状態ファイルが実際にディスクから削除される(
    tmp_path,
):
    """``resume.clear()``/``partial_store.clear()``がインメモリのクリアに留まらず、
    ``ResumeStore``の状態ディレクトリ上の実ファイル(``<resume_key>.json``・
    design.md「sapa.collector」State Management記載の部分結果キー
    ``sapa-partial.json``)が実際に削除されることを、ファイルシステムを直接
    確認して検証する(``tests/sapa/test_runner.py``のタスク5.2向け検証は
    ``resume_store.load(key)``経由のみで、実ファイルの存否までは確認して
    いなかった)。
    """
    url_a = "https://www.driveplaza.com/sapa/1010/3010001/1/"
    html_by_url = {
        _EAST_TOKYO_LISTING_URL: _listing_html([("テスト東京SA-成功(上り)", url_a)]),
        url_a: _detail_html(name="テスト東京SA-成功", road_name="中央自動車道", address="東京都新宿区西新宿2-8-4"),
    }
    session = _StubSession(html_by_url)
    fetcher = PageFetcher(_fast_config(), session=session)
    geocoder = _StubGeocoder(Coordinate(longitude=139.69, latitude=35.69))

    state_dir = tmp_path / ".resume"
    resume_key = "sapa-test-resume-clear-success"
    store = ResumeStore(state_dir=state_dir)
    resume = UrlResumeTracker(resume_key, store=store)
    partial_store = SapaPartialStore(store=store)
    output_dir = tmp_path / "geo-json"

    result = run_scope(
        ScopeSpec(prefecture_code="13"),
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

    # 7.3: インメモリの.clear()呼び出しに留まらず、実ファイルが消えている。
    assert not (state_dir / f"{resume_key}.json").exists()
    assert not (state_dir / "sapa-partial.json").exists()


def test_run_scopeの検証_一部サイトの一覧取得が失敗した場合_レジューム状態ファイルが削除されず保持される(tmp_path):
    """7.3の裏側: 実際の``CentralSite``の一覧取得がHTTP 500で失敗する状況
    (``EastSite``は成功)で、1件でもサイト失敗が残るためレジューム状態ファイルが
    削除されずディスク上に残ることを検証する(全成功時のみクリアされることの
    対偶)。``ALL_SITES``はモンキーパッチせず実際の東日本・中日本・西日本の
    3サイトをそのまま使う(``tests/sapa/test_integration_deletion.py``の
    サイト失敗隔離テストと同じ「実アダプタのまま」の方針。長野県は
    ``EastSite``のarealist=4・``CentralSite``の管轄が交差するため、この
    組み合わせで両方に実際のHTTPリクエストが発生する)。
    """
    url_nagano = "https://www.driveplaza.com/sapa/2020/3020001/1/"
    html_by_url = {
        _EAST_NAGANO_LISTING_URL: _listing_html([("テスト長野SA-成功(上り)", url_nagano)]),
        url_nagano: _detail_html(name="テスト長野SA-成功", road_name="長野自動車道", address="長野県松本市渚2-4-10"),
    }
    session = _StubSession(html_by_url, failure_status_by_url={_CENTRAL_SEARCH_URL: 500})
    fetcher = PageFetcher(_fast_config(), session=session)
    geocoder = _StubGeocoder(Coordinate(longitude=137.97, latitude=36.24))

    state_dir = tmp_path / ".resume"
    resume_key = "sapa-test-resume-clear-failure"
    store = ResumeStore(state_dir=state_dir)
    resume = UrlResumeTracker(resume_key, store=store)
    partial_store = SapaPartialStore(store=store)
    output_dir = tmp_path / "geo-json"

    result = run_scope(
        ScopeSpec(prefecture_code="20"),
        fetcher=fetcher,
        geocoder=geocoder,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_store,
    )

    assert isinstance(result, SapaScopeRunResult)
    assert result.failed_site_keys == frozenset({"central"})
    assert result.failed_prefecture_codes == frozenset()

    # 1件でもサイト失敗が残るため、レジューム状態・部分結果とも実ファイルが
    # 削除されずディスク上に残る。
    assert (state_dir / f"{resume_key}.json").exists()
    assert (state_dir / "sapa-partial.json").exists()

    reloaded_resume = UrlResumeTracker(resume_key, store=store)
    assert reloaded_resume.is_processed(url_nagano) is True
