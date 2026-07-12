"""連続するリクエスト間の最小待機時間を強制するレート制御。

呼び出し側が設定した最小待機時間(秒)を保持し、:meth:`RateLimiter.wait`
呼び出し時に、直前の ``wait`` 完了時刻からの経過時間が不足していれば
その分だけブロッキング待機する。単一スレッド・単一プロセスでの逐次呼び出しを
前提とする。
"""

from __future__ import annotations

import time

__all__ = ["RateLimiter"]


class RateLimiter:
    """最小リクエスト間隔を強制するレートリミッタ。"""

    def __init__(self, min_interval_seconds: float) -> None:
        """最小待機時間(秒)を受け取る。負値は :class:`ValueError` で拒否する。"""
        if min_interval_seconds < 0:
            raise ValueError(
                f"min_interval_secondsは0以上である必要があります: {min_interval_seconds}"
            )
        self._min_interval_seconds = min_interval_seconds
        self._last_wait_end: float | None = None

    def wait(self) -> None:
        """直前の ``wait`` から最小待機時間が経過するまで待機する。

        初回呼び出しは待機せず即座に返る。2回目以降は、直前の ``wait`` 完了時刻から
        最小待機時間以上が経過するまでブロッキング待機してから返る。
        """
        if self._last_wait_end is not None:
            elapsed = time.monotonic() - self._last_wait_end
            remaining = self._min_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_wait_end = time.monotonic()
