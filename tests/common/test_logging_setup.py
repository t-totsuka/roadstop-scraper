import logging

import pytest

from roadstop_scraper.common import logging_setup


@pytest.fixture
def capturing_logger() -> tuple[logging.Logger, list[logging.LogRecord]]:
    # ハンドラを直接付与して、propagate設定に依存せずレコードを捕捉する
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("test_logging_setup_target")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(_ListHandler())
    try:
        yield logger, records
    finally:
        logger.handlers.clear()


def test_ロガー取得の検証_名前指定でget_loggerが要求された場合_Loggerを返す():
    logger = logging_setup.get_logger("some.module")

    assert isinstance(logger, logging.Logger)


def test_開始ログの検証_log_scrape_startedが呼ばれた場合_INFOでtarget名を含む1件を出力する(capturing_logger):
    logger, records = capturing_logger

    logging_setup.log_scrape_started(logger, "hokkaido_michinoeki")

    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert "hokkaido_michinoeki" in records[0].getMessage()


def test_終了ログの検証_log_scrape_finishedが呼ばれた場合_INFOでtarget名と件数を含む1件を出力する(capturing_logger):
    logger, records = capturing_logger

    logging_setup.log_scrape_finished(logger, "hokkaido_michinoeki", 42)

    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    message = records[0].getMessage()
    assert "hokkaido_michinoeki" in message
    assert "42" in message


def test_失敗ログの検証_log_scrape_failedが呼ばれた場合_ERRORでtarget名とエラーを含む1件を出力する(capturing_logger):
    logger, records = capturing_logger

    logging_setup.log_scrape_failed(logger, "hokkaido_michinoeki", ValueError("boom"))

    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    message = records[0].getMessage()
    assert "hokkaido_michinoeki" in message
    assert "boom" in message
