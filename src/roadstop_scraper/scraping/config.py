"""スクレイピング動作設定の定義と ``pyproject.toml`` からの読み込み。

:class:`ScrapingConfig` は取得動作(タイムアウト・リトライ・リクエスト間隔)を
制御する不変の設定値をまとめる。:func:`load_scraping_config` は
``python_util.logging.config_loader`` と同型の探索(起点ディレクトリから
親方向へ ``pyproject.toml`` を探索する)を行うが、同モジュールは非公開のため
再利用せず本モジュール内に同型の実装を持つ。

設定の不備(テーブル・ファイル不在、キー省略、値の型不一致・負数、TOML構文
エラー)は例外を送出せず、該当項目を既定値に置き換えて動作を継続する
(設定ミスがレート制限の無効化や実行不能につながらないよう、常に安全側の
値で動作させるため)。ただしテーブル・ファイル自体が存在しないケースは
「設定なしの正常運用」であり警告は出さない。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roadstop_scraper.common.logging_setup import get_logger

__all__ = ["ScrapingConfig", "load_scraping_config"]

_logger = get_logger(__name__)

_TABLE_PATH = ("tool", "roadstop_scraper", "scraping")


@dataclass(frozen=True)
class ScrapingConfig:
    """取得動作を制御する不変の設定値。"""

    timeout_seconds: float = 10.0
    """HTTPリクエストのタイムアウト秒数。"""

    max_retries: int = 3
    """一時的な取得失敗(5xx・タイムアウト・接続エラー)時の最大リトライ回数。"""

    retry_wait_seconds: float = 1.0
    """リトライ前に空ける待機秒数。"""

    min_request_interval_seconds: float = 1.0
    """連続リクエスト間の最小間隔秒数(RateLimiterへ渡す値)。"""


def load_scraping_config(start_dir: Path | None = None) -> ScrapingConfig:
    """``[tool.roadstop_scraper.scraping]`` から設定を読み込む。

    起点ディレクトリ(既定は :func:`Path.cwd`)から親方向へ ``pyproject.toml``
    を探索する。ファイルが見つからない、またはテーブル自体が存在しない場合は
    「設定なしの正常運用」として警告なしに既定値を返す。テーブルが存在する
    場合は各キーを個別に検証し、省略・型不一致・負数のキーは既定値に
    置き換えたうえで警告ログを出す。TOMLの構文自体が不正な場合はファイル
    全体を無視し、全項目を既定値として警告ログを出す。いずれの経路でも
    例外は送出しない。
    """
    base_dir = start_dir if start_dir is not None else Path.cwd()
    pyproject_path = _find_pyproject_toml(base_dir)
    if pyproject_path is None:
        return ScrapingConfig()

    try:
        text = pyproject_path.read_text(encoding="utf-8")
        data = tomllib.loads(text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        _logger.warning(
            "%s の解析に失敗したため、スクレイピング設定は既定値で動作します: %s",
            pyproject_path,
            exc,
        )
        return ScrapingConfig()

    table = _extract_scraping_table(data)
    if table is None:
        return ScrapingConfig()

    defaults = ScrapingConfig()
    return ScrapingConfig(
        timeout_seconds=_resolve_non_negative_float(table, "timeout_seconds", defaults.timeout_seconds, pyproject_path),
        max_retries=_resolve_non_negative_int(table, "max_retries", defaults.max_retries, pyproject_path),
        retry_wait_seconds=_resolve_non_negative_float(
            table, "retry_wait_seconds", defaults.retry_wait_seconds, pyproject_path
        ),
        min_request_interval_seconds=_resolve_non_negative_float(
            table,
            "min_request_interval_seconds",
            defaults.min_request_interval_seconds,
            pyproject_path,
        ),
    )


def _find_pyproject_toml(start_dir: Path) -> Path | None:
    """起点ディレクトリから親方向へ ``pyproject.toml`` を探索する。"""
    current = start_dir
    while True:
        candidate = current / "pyproject.toml"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def _extract_scraping_table(data: dict[str, Any]) -> dict[str, Any] | None:
    """``data`` から ``[tool.roadstop_scraper.scraping]`` テーブルを取り出す。

    途中の階層が dict でない(想定外の型で書かれている)場合もテーブル
    不在として扱い、属性アクセスによる例外を起こさないようにする。
    """
    node: Any = data
    for key in _TABLE_PATH:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, dict) else None


def _resolve_non_negative_float(table: dict[str, Any], key: str, default: float, pyproject_path: Path) -> float:
    """テーブルから非負のfloat値を取り出す。省略・型不一致・負数は既定値+警告。"""
    if key not in table:
        _warn_fallback(pyproject_path, key, "キーが省略されています", default)
        return default

    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _warn_fallback(pyproject_path, key, f"数値ではありません: {value!r}", default)
        return default

    if value < 0:
        _warn_fallback(pyproject_path, key, f"負数は指定できません: {value!r}", default)
        return default

    return float(value)


def _resolve_non_negative_int(table: dict[str, Any], key: str, default: int, pyproject_path: Path) -> int:
    """テーブルから非負のint値を取り出す。省略・型不一致・負数は既定値+警告。"""
    if key not in table:
        _warn_fallback(pyproject_path, key, "キーが省略されています", default)
        return default

    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _warn_fallback(pyproject_path, key, f"整数ではありません: {value!r}", default)
        return default

    if value < 0:
        _warn_fallback(pyproject_path, key, f"負数は指定できません: {value!r}", default)
        return default

    return value


def _warn_fallback(pyproject_path: Path, key: str, reason: str, default: object) -> None:
    """設定キーが既定値へフォールバックしたことを警告ログとして記録する。"""
    _logger.warning(
        "%s の [tool.roadstop_scraper.scraping].%s は既定値 %s にフォールバックします(%s)",
        pyproject_path,
        key,
        default,
        reason,
    )
