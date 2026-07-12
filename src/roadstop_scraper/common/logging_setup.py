"""共通ロギングセットアップ。

`python_util.logging.get_logger` を共通のimportパスとして再公開し、
スクレイピング処理の開始・終了・失敗イベントを一貫したメッセージ形式で記録する
ヘルパー関数を提供する。
"""

from __future__ import annotations

import logging

# python_util側のget_loggerをそのまま再公開する(設定読み込み・フォールバックは
# python_util側の責務のため、本モジュールでは再実装しない)
from python_util.logging import get_logger

__all__ = [
    "get_logger",
    "log_scrape_started",
    "log_scrape_finished",
    "log_scrape_failed",
]


def log_scrape_started(logger: logging.Logger, target: str) -> None:
    """スクレイピング開始イベントをINFOで記録する。"""
    logger.info("スクレイピング開始: target=%s", target)


def log_scrape_finished(logger: logging.Logger, target: str, item_count: int) -> None:
    """スクレイピング終了イベントを取得件数付きでINFOで記録する。"""
    logger.info("スクレイピング終了: target=%s items=%d", target, item_count)


def log_scrape_failed(logger: logging.Logger, target: str, error: Exception) -> None:
    """スクレイピング失敗イベントをERRORで記録する。"""
    # exc_info=Errorでスタックトレースも併せて出力し、原因追跡を容易にする
    logger.error("スクレイピング失敗: target=%s error=%s", target, error, exc_info=error)
