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
from roadstop_scraper.scraping.extract import ExtractedRecord, FieldSpec, extract_record
from roadstop_scraper.scraping.fetcher import DEFAULT_USER_AGENT, FetchedContent, PageFetcher
from roadstop_scraper.scraping.parser import HtmlPage, parse_html
from roadstop_scraper.scraping.resume import UrlResumeTracker

__all__ = [
    "DEFAULT_USER_AGENT",
    "ContentParseError",
    "ExtractedRecord",
    "FetchFailedError",
    "FetchedContent",
    "FieldSpec",
    "HtmlPage",
    "PageFetcher",
    "ScrapingConfig",
    "ScrapingEngineError",
    "StructureChangedError",
    "UrlResumeTracker",
    "extract_record",
    "load_scraping_config",
    "parse_html",
]
