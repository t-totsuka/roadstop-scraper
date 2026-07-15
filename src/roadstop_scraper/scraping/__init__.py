"""スクレイピングエンジン(04-scraping-engine)の公開API。

利用側(05-michinoeki-scraping・06-sapa-scraping)はこのモジュールだけを
importすればよい。個別モジュール(``errors``・``config`` 等)への直接依存は
不要。
"""

from roadstop_scraper.scraping.config import ScrapingConfig, load_scraping_config
from roadstop_scraper.scraping.errors import (
    ContentParseError,
    FetchFailedError,
    ScrapingEngineError,
    StructureChangedError,
)

__all__ = [
    "ContentParseError",
    "FetchFailedError",
    "ScrapingConfig",
    "ScrapingEngineError",
    "StructureChangedError",
    "load_scraping_config",
]
