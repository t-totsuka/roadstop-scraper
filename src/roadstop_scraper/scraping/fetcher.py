"""レート制限・タイムアウト・リトライ付きHTTP取得(PageFetcher)。

`02-common-infra` の :class:`RateLimiter` による送信前待機と、
`roadstop_scraper.common.logging_setup.get_logger` による共通ロギングを内蔵した
唯一のHTTP取得経路を提供する。5xx・タイムアウト・接続エラーは一時的な障害として
`max_retries` 回まで `retry_wait_seconds` の間隔でリトライし、4xxは再送しても
結果が変わらないため即時に失敗を確定させる(要件2.4)。テスト時は
:class:`SessionLike` を満たす偽セッションを注入することで、追加のモック
ライブラリなしにHTTP層をスタブ化できる。
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import requests

from roadstop_scraper.common.logging_setup import get_logger
from roadstop_scraper.common.rate_limiter import RateLimiter
from roadstop_scraper.scraping.config import ScrapingConfig, load_scraping_config
from roadstop_scraper.scraping.errors import ContentParseError, FetchFailedError

__all__ = [
    "DEFAULT_USER_AGENT",
    "FetchedContent",
    "PageFetcher",
    "ResponseLike",
    "SessionLike",
]

# requests既定のUser-Agent("python-requests/x.y.z")は一部サイトでブロック対象と
# なりうるため、識別可能な独自UAを付与する。バージョンはpyproject.tomlの
# [project].versionに合わせた固定文字列とする(importlib.metadataによる動的解決は
# 設計上必須ではなく、editable install等での解決失敗リスクを避けるためあえて行わない)。
DEFAULT_USER_AGENT = "roadstop-scraper/0.1.0"

# Content-Typeヘッダからcharsetパラメータを取り出す正規表現(例: "text/html; charset=utf-8")
_CHARSET_PATTERN = re.compile(r"charset=([^\s;]+)", re.IGNORECASE)


class ResponseLike(Protocol):
    """``PageFetcher`` が必要とするHTTPレスポンスの最小インタフェース。"""

    status_code: int
    content: bytes
    headers: Mapping[str, str]
    apparent_encoding: str


class SessionLike(Protocol):
    """``PageFetcher`` が必要とするHTTPセッションの最小インタフェース。

    テスト時はこのプロトコルを満たす偽セッションを注入することで、追加の
    モックライブラリなしにHTTP層をスタブ化できる。
    """

    def get(self, url: str, *, timeout: float, headers: Mapping[str, str]) -> ResponseLike: ...


@dataclass(frozen=True)
class FetchedContent:
    """取得成功時の本文とメタ情報。"""

    url: str
    """取得元URL(6.2の source_url にそのまま使える)。"""

    text: str
    """エンコーディング解決済みの本文。"""

    encoding: str
    """解決に使ったエンコーディング名。"""


class PageFetcher:
    """レート制限・タイムアウト・リトライ・エンコーディング解決を内蔵した唯一のHTTP取得経路。"""

    def __init__(
        self,
        config: ScrapingConfig | None = None,
        *,
        rate_limiter: RateLimiter | None = None,
        session: SessionLike | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        # configを省略した場合はpyproject.tomlから読み込む(未設定時は既定値)
        self._config = config if config is not None else load_scraping_config()
        # rate_limiterを省略した場合はconfigの間隔で内部生成する(05/06が複数
        # Fetcherでサーバ単位の間隔を共有したい場合は明示的に注入する)
        self._rate_limiter = (
            rate_limiter if rate_limiter is not None else RateLimiter(self._config.min_request_interval_seconds)
        )
        # sessionを省略した場合は実際のrequests.Sessionを内部生成する
        self._session: SessionLike = session if session is not None else requests.Session()
        self._user_agent = user_agent
        self._logger = get_logger(__name__)

    def fetch_text(self, url: str) -> FetchedContent:
        """URLからHTML等のテキストコンテンツを取得する(要件1.1、1.4)。"""
        response = self._send_with_retry(url)
        encoding = _resolve_encoding(response)
        text = response.content.decode(encoding, errors="replace")
        return FetchedContent(url=url, text=text, encoding=encoding)

    def fetch_json(self, url: str) -> object:
        """URLからJSON形式のレスポンスを取得しパースする(要件1.2)。

        2xx応答のJSON構文が不正な場合は :class:`ContentParseError` を送出する。
        これはコンテンツ不正であり一時的な障害ではないためリトライしない。
        """
        response = self._send_with_retry(url)
        encoding = _resolve_encoding(response)
        text = response.content.decode(encoding, errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContentParseError(url) from exc

    def _send_with_retry(self, url: str) -> ResponseLike:
        """レート制限・タイムアウト・リトライを適用してHTTPリクエストを送信する。

        試行順序は「取得リトライフロー」のとおり: 初回はRateLimiter.waitの後に
        送信、2回目以降はretry_wait_seconds待機してからRateLimiter.waitを経て
        送信する(全試行がレート制限を通過する。要件1.3)。4xxは即時失敗、
        5xx・タイムアウト・接続エラーはmax_retries回まで再試行する(要件2.2-2.6)。
        """
        headers = {"User-Agent": self._user_agent}
        total_attempts = self._config.max_retries + 1

        for attempt in range(1, total_attempts + 1):
            if attempt > 1:
                self._logger.warning(
                    "取得リトライ: url=%s attempt=%d/%d",
                    url,
                    attempt,
                    total_attempts,
                )
                time.sleep(self._config.retry_wait_seconds)

            self._rate_limiter.wait()
            self._logger.debug("取得開始: url=%s attempt=%d/%d", url, attempt, total_attempts)

            try:
                response = self._session.get(url, timeout=self._config.timeout_seconds, headers=headers)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                if attempt < total_attempts:
                    continue
                self._logger.error("取得失敗: url=%s attempts=%d error=%s", url, attempt, exc)
                raise FetchFailedError(url, None, attempt) from exc
            except requests.exceptions.RequestException as exc:
                # URL不正(スキーム欠落等)・リダイレクト超過などその他のrequests
                # 例外は再送しても解消しないため、リトライせず即時確定する。
                # ここで捕捉しないとエンジンの契約(全失敗モードを
                # ScrapingEngineErrorへ正規化する)から漏れ、利用側の
                # 都道府県単位・道の駅単位の継続処理が機能しない。
                self._logger.error("取得失敗: url=%s attempts=%d error=%s", url, attempt, exc)
                raise FetchFailedError(url, None, attempt) from exc

            status = response.status_code
            if 200 <= status < 300:
                self._logger.info("取得成功: url=%s status_code=%d attempts=%d", url, status, attempt)
                return response
            if 400 <= status < 500:
                # クライアントエラーは再送しても結果が変わらないため即時確定する
                self._logger.error(
                    "取得失敗: url=%s status_code=%d attempts=%d",
                    url,
                    status,
                    attempt,
                )
                raise FetchFailedError(url, status, attempt)

            # 5xx等は一時的な障害としてリトライ対象とする(上限に達していれば確定)
            if attempt >= total_attempts:
                self._logger.error(
                    "取得失敗: url=%s status_code=%d attempts=%d",
                    url,
                    status,
                    attempt,
                )
                raise FetchFailedError(url, status, attempt)

        # 上のループはtotal_attempts回以内で必ずreturn/raiseするため到達しない
        raise AssertionError("到達しないはずのコードパスです")


def _resolve_encoding(response: ResponseLike) -> str:
    """Content-Typeヘッダのcharsetを優先し、無指定時はapparent_encodingへフォールバックする(要件1.4)。"""
    content_type = _get_header(response.headers, "Content-Type")
    if content_type is not None:
        match = _CHARSET_PATTERN.search(content_type)
        if match is not None:
            return match.group(1).strip("\"'")
    return response.apparent_encoding


def _get_header(headers: Mapping[str, str], name: str) -> str | None:
    """大文字小文字を無視してヘッダ値を取得する。"""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None
