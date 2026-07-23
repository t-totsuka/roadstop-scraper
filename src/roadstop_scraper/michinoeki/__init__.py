"""道の駅スクレイパー(05-michinoeki-scraping)の公開API。

利用側(エントリポイント)はこのモジュールだけをimportすればよい。個別モジュール
(``site_urls``・``listing``・``detail``・``runner``・``cli`` 等)への直接依存は
不要。実行対象範囲の解決(``scope``)・削除状態遷移(``merge``)は共有層
``roadstop_scraper.pipeline``へ移設済みで、本モジュールはそこから再公開する
(公開名は移設前と同一)。

``site_urls``(``SITE_PREFECTURE_CODES``・``build_search_url``)は対象サイト固有の
URL構築に関する内部実装詳細であり、利用側が直接参照する必要はないため
再公開しない(design.md「Architecture」節、Boundary Commitments参照)。
"""

from roadstop_scraper.michinoeki.cli import main
from roadstop_scraper.michinoeki.detail import extract_station_properties
from roadstop_scraper.michinoeki.listing import (
    ListingResult,
    ListingUnavailableError,
    StationStub,
    fetch_station_stubs,
)
from roadstop_scraper.michinoeki.runner import PrefectureRunResult, run_prefecture, run_scope
from roadstop_scraper.pipeline import (
    REGIONS,
    InvalidScopeError,
    MergeResult,
    ScopeSpec,
    merge_with_previous,
    resolve_scope,
)

__all__ = [
    "REGIONS",
    "InvalidScopeError",
    "ListingResult",
    "ListingUnavailableError",
    "MergeResult",
    "PrefectureRunResult",
    "ScopeSpec",
    "StationStub",
    "extract_station_properties",
    "fetch_station_stubs",
    "main",
    "merge_with_previous",
    "resolve_scope",
    "run_prefecture",
    "run_scope",
]
