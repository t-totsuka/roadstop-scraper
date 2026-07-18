import logging
from pathlib import Path

from roadstop_scraper.scraping.config import ScrapingConfig, load_scraping_config


def _write_pyproject(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_探索の検証_pyprojecttomlが見つからない場合_既定値を返し警告を出さない(tmp_path: Path, caplog):
    # 起点ディレクトリの親を辿ってもpyproject.tomlが存在しないケース
    start_dir = tmp_path / "nested" / "dir"
    start_dir.mkdir(parents=True)

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.scraping.config"):
        config = load_scraping_config(start_dir=start_dir)

    assert config == ScrapingConfig()
    assert caplog.records == []


def test_探索の検証_pyprojecttomlはあるが対象テーブルがない場合_既定値を返し警告を出さない(tmp_path: Path, caplog):
    # pyproject.tomlは存在するが[tool.roadstop_scraper.scraping]テーブルがないケース
    _write_pyproject(tmp_path, '[project]\nname = "dummy"\n')

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.scraping.config"):
        config = load_scraping_config(start_dir=tmp_path)

    assert config == ScrapingConfig()
    assert caplog.records == []


def test_探索の検証_親ディレクトリのpyprojecttomlも発見できる(tmp_path: Path):
    # start_dirの親方向へ探索することを確認する(python_util.logging.config_loaderと同型)
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
timeout_seconds = 20.0
""",
    )
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    config = load_scraping_config(start_dir=nested)

    assert config.timeout_seconds == 20.0


def test_読み込みの検証_テーブルの全キーが有効な場合_その値を使用する(tmp_path: Path):
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
timeout_seconds = 30.0
max_retries = 5
retry_wait_seconds = 2.5
min_request_interval_seconds = 0.5
""",
    )

    config = load_scraping_config(start_dir=tmp_path)

    assert config == ScrapingConfig(
        timeout_seconds=30.0,
        max_retries=5,
        retry_wait_seconds=2.5,
        min_request_interval_seconds=0.5,
    )


def test_読み込みの検証_一部のキーが整数で有効な値の場合_float型に変換して使用する(
    tmp_path: Path,
):
    # timeout_seconds等はint値(TOML上のリテラル型)でも数値として受理する
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
timeout_seconds = 15
""",
    )

    config = load_scraping_config(start_dir=tmp_path)

    assert config.timeout_seconds == 15.0
    assert isinstance(config.timeout_seconds, float)


def test_読み込みの検証_一部のキーが省略された場合_省略キーのみ既定値にフォールバックし警告を出す(
    tmp_path: Path, caplog
):
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
timeout_seconds = 30.0
max_retries = 5
""",
    )

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.scraping.config"):
        config = load_scraping_config(start_dir=tmp_path)

    assert config == ScrapingConfig(
        timeout_seconds=30.0,
        max_retries=5,
        retry_wait_seconds=ScrapingConfig().retry_wait_seconds,
        min_request_interval_seconds=ScrapingConfig().min_request_interval_seconds,
    )
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 2


def test_読み込みの検証_値が負数の場合_その項目のみ既定値にフォールバックし警告を出す(tmp_path: Path, caplog):
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
timeout_seconds = -1.0
max_retries = 3
retry_wait_seconds = 1.0
min_request_interval_seconds = 1.0
""",
    )

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.scraping.config"):
        config = load_scraping_config(start_dir=tmp_path)

    assert config.timeout_seconds == ScrapingConfig().timeout_seconds
    assert config.max_retries == 3
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "timeout_seconds" in warning_records[0].getMessage()


def test_読み込みの検証_max_retriesが負数の場合_その項目のみ既定値にフォールバックし警告を出す(tmp_path: Path, caplog):
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
timeout_seconds = 10.0
max_retries = -2
retry_wait_seconds = 1.0
min_request_interval_seconds = 1.0
""",
    )

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.scraping.config"):
        config = load_scraping_config(start_dir=tmp_path)

    assert config.max_retries == ScrapingConfig().max_retries
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "max_retries" in warning_records[0].getMessage()


def test_読み込みの検証_値の型が不正な場合_その項目のみ既定値にフォールバックし警告を出す(tmp_path: Path, caplog):
    # 数値項目に文字列を指定した型不一致のケース
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
retry_wait_seconds = "fast"
""",
    )

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.scraping.config"):
        config = load_scraping_config(start_dir=tmp_path)

    assert config.retry_wait_seconds == ScrapingConfig().retry_wait_seconds
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("retry_wait_seconds" in r.getMessage() for r in warning_records)


def test_読み込みの検証_max_retriesがfloatの場合_型不一致として既定値にフォールバックする(tmp_path: Path, caplog):
    # max_retriesは非負整数のみを許容する(floatは型不一致)
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
timeout_seconds = 10.0
max_retries = 3.5
retry_wait_seconds = 1.0
min_request_interval_seconds = 1.0
""",
    )

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.scraping.config"):
        config = load_scraping_config(start_dir=tmp_path)

    assert config.max_retries == ScrapingConfig().max_retries
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1


def test_読み込みの検証_TOML構文が不正な場合_全項目既定値にフォールバックし警告を出し例外を送出しない(
    tmp_path: Path, caplog
):
    _write_pyproject(tmp_path, "[tool.roadstop_scraper.scraping\nbroken = ")

    with caplog.at_level(logging.WARNING, logger="roadstop_scraper.scraping.config"):
        config = load_scraping_config(start_dir=tmp_path)

    assert config == ScrapingConfig()
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1


def test_既定値の検証_start_dir省略時はNoneを渡した場合と同様にcwdから探索する(tmp_path: Path, monkeypatch):
    _write_pyproject(
        tmp_path,
        """
[tool.roadstop_scraper.scraping]
timeout_seconds = 42.0
""",
    )
    monkeypatch.chdir(tmp_path)

    config = load_scraping_config()

    assert config.timeout_seconds == 42.0


def test_既定値の検証_ScrapingConfigは不変であるフィールド代入不可(tmp_path: Path):
    import dataclasses

    config = ScrapingConfig()

    assert dataclasses.is_dataclass(config)
    try:
        config.timeout_seconds = 99.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("ScrapingConfigはfrozenでなければならない")
