"""HTTP取得とURL単位のレジューム管理の結合検証(タスク3.3)。

design.md「Integration Tests」の「``UrlResumeTracker``+``PageFetcher``の組み合わせで、
処理済みURLがスキップされ未処理のみ取得されること」を検証する(要件5.3・5.4)。

design.mdの「Out of Boundary」・Componentsテーブルには、両者を自動的に配線する
オーケストレータ的な部品は存在しない(サイト単位のURL列挙・処理ループは
05-michinoeki-scraping/06-sapa-scrapingの責務)。本テストはその将来の利用側が
行うであろう「``tracker.is_processed``でスキップ判定→未処理のみ``fetcher.fetch_text``→
``tracker.mark_processed``で記録」という最小ループをテストコード自身の中に用意し、
``PageFetcher``(偽セッション注入)と実体の``UrlResumeTracker``(実``ResumeStore``を
``tmp_path``に向けたもの)を実際に組み合わせて動かすことで結合を検証する
(test_fetcher.pyの偽セッション方式、test_resume.pyの実ResumeStore方式をそのまま踏襲)。
"""

from __future__ import annotations

from pathlib import Path

from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.scraping.config import ScrapingConfig
from roadstop_scraper.scraping.fetcher import PageFetcher
from roadstop_scraper.scraping.resume import UrlResumeTracker

_ALL_URLS = [
    "https://example.com/a",
    "https://example.com/b",
    "https://example.com/c",
    "https://example.com/d",
    "https://example.com/e",
]

# 事前に処理済みとして記録しておくURL(5件中2件)。残り3件が今回の実行で新規に取得される。
_PRE_PROCESSED_URLS = [
    "https://example.com/a",
    "https://example.com/c",
]

_UNPROCESSED_URLS = [url for url in _ALL_URLS if url not in _PRE_PROCESSED_URLS]

_RESUME_KEY = "michinoeki"


class _FakeResponse:
    """``ResponseLike``を満たす偽レスポンス(test_fetcher.pyと同じ形)。"""

    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.apparent_encoding = "utf-8"


class _FakeSession:
    """呼び出されたURLを記録し、常に2xxを返す偽セッション(test_fetcher.pyと同じ形)。"""

    def __init__(self) -> None:
        self.requested_urls: list[str] = []

    def get(self, url, *, timeout, headers):
        self.requested_urls.append(url)
        return _FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"})


class _FakeRateLimiter:
    """試験を高速化するため、待機せず呼び出し回数のみ記録する偽RateLimiter(既存パターンと同じ)。"""

    def __init__(self) -> None:
        self.wait_count = 0

    def wait(self) -> None:
        self.wait_count += 1


def _fast_config() -> ScrapingConfig:
    return ScrapingConfig(
        timeout_seconds=5.0,
        max_retries=0,
        retry_wait_seconds=0.0,
        min_request_interval_seconds=0.0,
    )


def test_結合検証_処理済みURLが事前記録されている場合_未処理URLのみ取得され全URLが処理済みになる(
    tmp_path: Path,
) -> None:
    # 準備: 実ResumeStore(tmp_path)を使い、5件中2件を「前回実行で処理済み」として先に記録しておく
    store = ResumeStore(state_dir=tmp_path)
    tracker = UrlResumeTracker(_RESUME_KEY, store=store)
    for url in _PRE_PROCESSED_URLS:
        tracker.mark_processed(url)

    session = _FakeSession()
    fetcher = PageFetcher(_fast_config(), rate_limiter=_FakeRateLimiter(), session=session)

    # 実行: 05/06が将来行うであろう最小の処理ループを、このテストの中で実際に動かす
    # (design.mdのBoundary Commitments上、このループ自体は本specのプロダクションコードにはしない)。
    for url in _ALL_URLS:
        if tracker.is_processed(url):
            continue
        fetcher.fetch_text(url)
        tracker.mark_processed(url)

    # 検証1(5.3): 事前に処理済みだった2件は取得対象から除外され、未処理だった3件のみ実際に取得された
    assert session.requested_urls == _UNPROCESSED_URLS

    # 検証2(5.4): ループ完了後は5件全てが処理済みとして判定できる(元々の2件+新規の3件)
    for url in _ALL_URLS:
        assert tracker.is_processed(url) is True

    # 検証3(5.4の永続化意図): 同一key・同一storeで新規にUrlResumeTrackerを再構築しても、
    # 「セッション」を跨いで5件全ての処理済み状態が実際に永続化されていることを確認する
    rebuilt_tracker = UrlResumeTracker(_RESUME_KEY, store=store)
    for url in _ALL_URLS:
        assert rebuilt_tracker.is_processed(url) is True
