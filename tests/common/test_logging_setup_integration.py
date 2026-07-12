"""共通ロギングセットアップの統合検証(タスク3.2)。

``logging_setup.get_logger`` 経由で取得したロガーが、本プロジェクトの
``pyproject.toml`` に ``[tool.python_util.logging]`` が設定されていない状態
(未設定時のデフォルト)で、``python_util.logging`` の規定どおり
「コンソール出力・レベル ``INFO``・ファイル出力なし」に構成されることを
確認する。個々のヘルパー関数の単体挙動は ``test_logging_setup.py`` で
検証済みのため、ここでは設定読み込みからハンドラ構成までの結合を対象とする。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from rich.logging import RichHandler

from python_util.logging import factory
from roadstop_scraper.common import logging_setup


@pytest.fixture
def fresh_logging_registry() -> Iterator[None]:
    # python_util 側は設定・構成済みロガーをモジュール内にキャッシュするため、
    # 実 pyproject.toml からの再読み込みを保証すべく前後でレジストリを初期化する
    factory._reset_registry()
    try:
        yield
    finally:
        factory._reset_registry()


def test_デフォルト設定の検証_設定未指定でget_loggerした場合_INFOのコンソール出力のみで構成される(
    fresh_logging_registry: None,
):
    logger = logging_setup.get_logger("roadstop_scraper.test.default_logging")

    # コンソール出力(RichHandler)がちょうど1件、レベル INFO で付与されている
    console_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]
    assert len(console_handlers) == 1
    assert console_handlers[0].level == logging.INFO

    # file 未設定のため、ファイル出力ハンドラは付与されない
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_デフォルト設定の検証_設定未指定のロガーは_INFO以上を出力しDEBUGは閾値未満となる(
    fresh_logging_registry: None,
):
    logger = logging_setup.get_logger("roadstop_scraper.test.default_level")
    console_handler = next(h for h in logger.handlers if isinstance(h, RichHandler))

    # 実際の出力可否を決めるコンソールハンドラのレベルが INFO であり、
    # INFO は出力対象・DEBUG は閾値未満(非出力)となる
    assert console_handler.level <= logging.INFO
    assert console_handler.level > logging.DEBUG
