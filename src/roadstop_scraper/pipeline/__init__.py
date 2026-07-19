"""実行時関心の共有層(pipeline)の公開API。

05-michinoeki-scraping・06-sapa-scraping双方から利用される、実行対象範囲の
解決(``scope``)と削除状態遷移(``merge``)を提供する。利用側はこのモジュール
だけをimportすればよい。個別モジュール(``scope``・``merge``)への直接依存は
不要。

``geojson/``のみに依存し、``scraping/``・site固有パッケージ(``michinoeki/``等)
へは依存しない(design.md「Boundary Commitments」Allowed Dependencies参照)。
"""

from roadstop_scraper.pipeline.merge import MergeResult, merge_with_previous
from roadstop_scraper.pipeline.scope import REGIONS, InvalidScopeError, ScopeSpec, resolve_scope

__all__ = [
    "REGIONS",
    "InvalidScopeError",
    "MergeResult",
    "ScopeSpec",
    "merge_with_previous",
    "resolve_scope",
]
