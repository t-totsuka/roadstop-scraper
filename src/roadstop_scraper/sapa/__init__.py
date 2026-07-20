"""SA/PAスクレイパー(06-sapa-scraping)の公開API。

NEXCO東日本・中日本・西日本のSA/PA(サービスエリア・パーキングエリア)公式
サイトから位置情報・名称・付加情報を収集し、都道府県単位のGeoJSONとして
出力する機能を提供する。実行対象範囲の解決・削除状態遷移は共有層
``roadstop_scraper.pipeline``を利用する(design.md「Boundary Commitments」
Allowed Dependencies参照)。

利用側(エントリポイント)はこのモジュールだけをimportすればよい。個別
モジュール(``collector``・``geocoding``・``runner``・``cli``・``sites``等)への
直接依存は不要(``michinoeki``パッケージと同じ再公開の規約)。
"""

from roadstop_scraper.sapa.cli import main
from roadstop_scraper.sapa.runner import (
    SapaPrefectureResult,
    SapaScopeRunResult,
    run_prefecture,
    run_prefectures,
    run_scope,
)

__all__ = [
    "SapaPrefectureResult",
    "SapaScopeRunResult",
    "main",
    "run_prefecture",
    "run_prefectures",
    "run_scope",
]
