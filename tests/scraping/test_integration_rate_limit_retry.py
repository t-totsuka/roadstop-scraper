"""リクエスト頻度制御とリトライ待機の重畳検証(タスク3.2)。

design.md「Integration Tests」の以下2項目を、実時間(``time.monotonic``・
実際の``time.sleep``)で検証する: 「``RateLimiter``実物を使った連続
``fetch_text``で最小間隔が保たれること(短い間隔値で実時間検証)」および
「リトライ待機とレート制限の重畳(リトライ経路でも間隔が縮まらないこと)」
(要件1.3・2.5)。

HTTP層は``SessionLike``を満たす偽セッションの注入でスタブ化するが(実ネットワーク
アクセスはしない)、``RateLimiter``は``PageFetcher``にconfigのみを渡して内部生成
させた実物を使う(test_fetcher.pyの単体テストが``_FakeRateLimiter``でwait回数のみを
検証するのとは異なり、ここでは実際の待機時間そのものを実時間で計測する)。
"""

from __future__ import annotations

import time
from itertools import pairwise

from roadstop_scraper.scraping.config import ScrapingConfig
from roadstop_scraper.scraping.fetcher import PageFetcher

# time.sleep/time.monotonicの実時間計測に許容する誤差(スケジューリングの揺らぎ対策)。
# 設定する間隔(0.05〜0.15秒程度)に対して十分小さく、タイミング退行を検知できる値とする。
_TOLERANCE_SECONDS = 0.01


class _FakeResponse:
    """``ResponseLike``を満たす偽レスポンス(test_fetcher.pyと同じ形)。"""

    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.apparent_encoding = "utf-8"


class _AlwaysOkSession:
    """常に2xx応答を返す偽セッション。各``get``呼び出し時刻を実時間で記録する。"""

    def __init__(self) -> None:
        self.call_times: list[float] = []

    def get(self, url, *, timeout, headers):
        # 送信直前(RateLimiter.wait通過直後)の実時刻を記録する
        self.call_times.append(time.monotonic())
        return _FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"})


class _FailThenOkSession:
    """1回目は5xx、2回目は2xxを返す偽セッション。各``get``呼び出し時刻を実時間で記録する。"""

    def __init__(self) -> None:
        self._responses: list[object] = [
            _FakeResponse(503, b"error"),
            _FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"}),
        ]
        self.call_times: list[float] = []

    def get(self, url, *, timeout, headers):
        self.call_times.append(time.monotonic())
        return self._responses.pop(0)


def test_レート制限の実時間検証_RateLimiter実物を用いた連続取得の場合_試行間隔がmin_request_interval_seconds以上になる():
    # What: rate_limiterを注入せず、configのmin_request_interval_secondsからPageFetcherに
    # 実物のRateLimiterを内部生成させ、連続する3回のfetch_textの送信間隔を実時間で計測する。
    min_interval = 0.08
    config = ScrapingConfig(
        timeout_seconds=5.0,
        max_retries=0,
        retry_wait_seconds=0.0,
        min_request_interval_seconds=min_interval,
    )
    session = _AlwaysOkSession()
    fetcher = PageFetcher(config, session=session)

    for _ in range(3):
        fetcher.fetch_text("https://example.com/rate-limit-check")

    assert len(session.call_times) == 3
    # What: 連続する各試行間の実経過時間が、いずれもmin_request_interval_seconds以上であること(1.3)。
    for previous, current in pairwise(session.call_times):
        elapsed = current - previous
        assert elapsed >= min_interval - _TOLERANCE_SECONDS, (
            f"連続する取得試行の間隔が最小リクエスト間隔を下回りました: elapsed={elapsed}, min_interval={min_interval}"
        )


def test_リトライ待機とレート制限の重畳検証_リトライ経由での再送の場合_試行間隔がretry_wait_secondsとmin_request_interval_seconds双方以上になる():
    # What: 1回目5xx→2回目2xxで成功する単一のfetch_text呼び出しにおいて、リトライ待機
    # (retry_wait_seconds)経過後もRateLimiter実物による最小間隔(min_request_interval_seconds)
    # が独立して働き、間隔が縮まらないことを実時間で検証する。min_request_intervalをretry_waitより
    # 大きく設定し、「リトライ待機が終わってもレート制限がバイパスされない」ことを明確化する。
    retry_wait = 0.05
    min_interval = 0.12
    config = ScrapingConfig(
        timeout_seconds=5.0,
        max_retries=1,
        retry_wait_seconds=retry_wait,
        min_request_interval_seconds=min_interval,
    )
    session = _FailThenOkSession()
    fetcher = PageFetcher(config, session=session)

    fetcher.fetch_text("https://example.com/retry-rate-limit-check")

    assert len(session.call_times) == 2
    elapsed = session.call_times[1] - session.call_times[0]
    # What: リトライ待機(2.5)が実際に実時間で発生したこと。
    assert elapsed >= retry_wait - _TOLERANCE_SECONDS, (
        f"リトライ待機が実時間で発生していません: elapsed={elapsed}, retry_wait={retry_wait}"
    )
    # What: リトライ経路でも最小リクエスト間隔(1.3)が保たれ、レート制限がバイパスされていないこと。
    # retry_wait単独の待機では満たせないmin_intervalまで、RateLimiterの待機が加算されて到達することを確認する。
    assert elapsed >= min_interval - _TOLERANCE_SECONDS, (
        f"リトライ経路でレート制限がバイパスされ間隔が縮まりました: elapsed={elapsed}, min_interval={min_interval}"
    )
