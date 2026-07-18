"""PageFetcherのユニットテスト。

HTTP層は``SessionLike``を満たす偽セッションの注入でスタブ化し、追加の
モックライブラリは導入しない(design.mdのテスト方針に準拠)。
"""

from __future__ import annotations

import json
import logging

import pytest
import requests

from roadstop_scraper.scraping.config import ScrapingConfig
from roadstop_scraper.scraping.errors import ContentParseError, FetchFailedError
from roadstop_scraper.scraping.fetcher import PageFetcher


class _FakeResponse:
    """``ResponseLike``を満たす偽レスポンス。"""

    def __init__(
        self,
        status_code: int,
        content: bytes,
        headers: dict[str, str] | None = None,
        apparent_encoding: str = "utf-8",
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.apparent_encoding = apparent_encoding


class _FakeSession:
    """事前に登録した応答(または例外)を呼び出し順に返す偽セッション。"""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url, *, timeout, headers):
        self.calls.append({"url": url, "timeout": timeout, "headers": headers})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeRateLimiter:
    """``wait``の呼び出し回数のみを記録する偽RateLimiter。"""

    def __init__(self) -> None:
        self.wait_count = 0

    def wait(self) -> None:
        self.wait_count += 1


def _config(**overrides: object) -> ScrapingConfig:
    base = {
        "timeout_seconds": 5.0,
        "max_retries": 2,
        "retry_wait_seconds": 0.0,
        "min_request_interval_seconds": 0.0,
    }
    base.update(overrides)
    return ScrapingConfig(**base)


_LOGGER_NAME = "roadstop_scraper.scraping.fetcher"


def test_取得の検証_2xx応答の場合_FetchedContentを返す():
    session = _FakeSession(
        [_FakeResponse(200, b"<html>ok</html>", headers={"Content-Type": "text/html; charset=utf-8"})]
    )
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    result = fetcher.fetch_text("https://example.com/page")

    assert result.url == "https://example.com/page"
    assert result.text == "<html>ok</html>"
    assert result.encoding == "utf-8"
    assert len(session.calls) == 1


def test_取得の検証_4xx応答の場合_即時にFetchFailedErrorを送出しリトライしない():
    session = _FakeSession([_FakeResponse(404, b"not found")])
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    with pytest.raises(FetchFailedError) as exc_info:
        fetcher.fetch_text("https://example.com/missing")

    assert exc_info.value.url == "https://example.com/missing"
    assert exc_info.value.status_code == 404
    assert exc_info.value.attempts == 1
    assert len(session.calls) == 1


def test_取得の検証_5xx応答が上限まで続く場合_最大回数リトライ後にFetchFailedErrorを送出する():
    max_retries = 2
    responses = [_FakeResponse(503, b"error") for _ in range(max_retries + 1)]
    session = _FakeSession(responses)
    fetcher = PageFetcher(_config(max_retries=max_retries), rate_limiter=_FakeRateLimiter(), session=session)

    with pytest.raises(FetchFailedError) as exc_info:
        fetcher.fetch_text("https://example.com/flaky")

    assert exc_info.value.status_code == 503
    assert exc_info.value.attempts == max_retries + 1
    assert len(session.calls) == max_retries + 1


def test_取得の検証_5xxの後に2xxが返る場合_リトライ後に成功する():
    session = _FakeSession(
        [
            _FakeResponse(503, b"error"),
            _FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"}),
        ]
    )
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    result = fetcher.fetch_text("https://example.com/retry-then-ok")

    assert result.text == "ok"
    assert len(session.calls) == 2


def test_取得の検証_タイムアウトはリトライ対象として扱われ最終的に成功する():
    session = _FakeSession(
        [
            requests.exceptions.Timeout("timed out"),
            _FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"}),
        ]
    )
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    result = fetcher.fetch_text("https://example.com/timeout-then-ok")

    assert result.text == "ok"
    assert len(session.calls) == 2


def test_取得の検証_接続エラーが上限まで続く場合_status_codeがNoneのFetchFailedErrorを送出する():
    max_retries = 1
    session = _FakeSession([requests.exceptions.ConnectionError("refused") for _ in range(max_retries + 1)])
    fetcher = PageFetcher(_config(max_retries=max_retries), rate_limiter=_FakeRateLimiter(), session=session)

    with pytest.raises(FetchFailedError) as exc_info:
        fetcher.fetch_text("https://example.com/unreachable")

    assert exc_info.value.status_code is None
    assert exc_info.value.attempts == max_retries + 1
    assert len(session.calls) == max_retries + 1


def test_レート制限の検証_リトライを含む全試行がRateLimiterのwaitを通過する():
    max_retries = 2
    responses = [_FakeResponse(503, b"error") for _ in range(max_retries + 1)]
    session = _FakeSession(responses)
    rate_limiter = _FakeRateLimiter()
    fetcher = PageFetcher(_config(max_retries=max_retries), rate_limiter=rate_limiter, session=session)

    with pytest.raises(FetchFailedError):
        fetcher.fetch_text("https://example.com/flaky")

    assert rate_limiter.wait_count == max_retries + 1


def test_リトライの検証_retry_wait_seconds分だけ待機してから再送する(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("roadstop_scraper.scraping.fetcher.time.sleep", lambda seconds: sleeps.append(seconds))
    session = _FakeSession(
        [
            _FakeResponse(503, b"error"),
            _FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"}),
        ]
    )
    fetcher = PageFetcher(
        _config(max_retries=1, retry_wait_seconds=2.5), rate_limiter=_FakeRateLimiter(), session=session
    )

    fetcher.fetch_text("https://example.com/wait-check")

    assert sleeps == [2.5]


def test_エンコーディング解決の検証_ContentTypeヘッダのcharsetを優先する():
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                "こんにちは".encode("shift_jis"),
                headers={"Content-Type": "text/html; charset=shift_jis"},
                apparent_encoding="utf-8",
            )
        ]
    )
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    result = fetcher.fetch_text("https://example.com/sjis")

    assert result.encoding == "shift_jis"
    assert result.text == "こんにちは"


def test_エンコーディング解決の検証_ContentTypeにcharsetがない場合_apparent_encodingへフォールバックする():
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                b"hello",
                headers={"Content-Type": "text/html"},
                apparent_encoding="utf-8",
            )
        ]
    )
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    result = fetcher.fetch_text("https://example.com/no-charset")

    assert result.encoding == "utf-8"
    assert result.text == "hello"


def test_エンコーディング解決の検証_ContentTypeヘッダ自体がない場合_apparent_encodingへフォールバックする():
    session = _FakeSession([_FakeResponse(200, b"hello", headers={}, apparent_encoding="utf-8")])
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    result = fetcher.fetch_text("https://example.com/no-content-type-header")

    assert result.encoding == "utf-8"
    assert result.text == "hello"


def test_JSON取得の検証_正常なJSONボディの場合_パース結果を返す():
    body = json.dumps({"facilities": [{"name": "テスト施設"}]}).encode("utf-8")
    session = _FakeSession([_FakeResponse(200, body, headers={"Content-Type": "application/json; charset=utf-8"})])
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    result = fetcher.fetch_json("https://example.com/data.json")

    assert result == {"facilities": [{"name": "テスト施設"}]}


def test_JSON取得の検証_不正なJSONボディの場合_ContentParseErrorを送出しリトライしない():
    session = _FakeSession([_FakeResponse(200, b"{not valid json", headers={"Content-Type": "application/json"})])
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    with pytest.raises(ContentParseError) as exc_info:
        fetcher.fetch_json("https://example.com/broken.json")

    assert exc_info.value.url == "https://example.com/broken.json"
    assert len(session.calls) == 1


def test_ログの検証_取得開始はDEBUGレベルでURLを含めて記録する(caplog):
    session = _FakeSession([_FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"})])
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        fetcher.fetch_text("https://example.com/log-start")

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug_records) == 1
    assert "https://example.com/log-start" in debug_records[0].getMessage()


def test_ログの検証_取得成功はINFOレベルでURLを含めて記録する(caplog):
    session = _FakeSession([_FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"})])
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        fetcher.fetch_text("https://example.com/log-success")

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert "https://example.com/log-success" in info_records[0].getMessage()


def test_ログの検証_リトライはWARNINGレベルでURLを含めて記録する(caplog):
    session = _FakeSession(
        [
            _FakeResponse(503, b"error"),
            _FakeResponse(200, b"ok", headers={"Content-Type": "text/plain; charset=utf-8"}),
        ]
    )
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        fetcher.fetch_text("https://example.com/log-retry")

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "https://example.com/log-retry" in warning_records[0].getMessage()


def test_ログの検証_最終失敗はERRORレベルでURLを含めて記録する(caplog):
    session = _FakeSession([_FakeResponse(404, b"not found")])
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
        with pytest.raises(FetchFailedError):
            fetcher.fetch_text("https://example.com/log-failure")

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    assert "https://example.com/log-failure" in error_records[0].getMessage()


def test_取得の検証_URL不正等のRequestExceptionの場合_即時にFetchFailedErrorを送出しリトライしない():
    """スキーム欠落(MissingSchema)等、タイムアウト・接続エラー以外のrequests例外も
    エンジンの契約どおりFetchFailedErrorへ正規化されることを検証する。素通りすると
    ScrapingEngineErrorを前提とする利用側(05/06)の継続処理が機能しない
    (実サイト疎通確認で検出された回帰のテスト)。
    """
    session = _FakeSession([requests.exceptions.MissingSchema("Invalid URL '/stations/views/1'")])
    fetcher = PageFetcher(_config(), rate_limiter=_FakeRateLimiter(), session=session)

    with pytest.raises(FetchFailedError) as exc_info:
        fetcher.fetch_text("/stations/views/1")

    assert exc_info.value.url == "/stations/views/1"
    assert exc_info.value.status_code is None
    assert exc_info.value.attempts == 1
    # 再送しても解消しないためリトライせず1回で確定する。
    assert len(session.calls) == 1
