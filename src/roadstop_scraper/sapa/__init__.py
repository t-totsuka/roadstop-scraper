"""SA/PAスクレイパー(06-sapa-scraping)の公開API。

NEXCO東日本・中日本・西日本のSA/PA(サービスエリア・パーキングエリア)公式
サイトから位置情報・名称・付加情報を収集し、都道府県単位のGeoJSONとして
出力する機能を提供する。実行対象範囲の解決・削除状態遷移は共有層
``roadstop_scraper.pipeline``を利用する(design.md「Boundary Commitments」
Allowed Dependencies参照)。

現時点ではパッケージの雛形のみで、収集・ジオコーディング・出力の実装は
後続タスク(2.x〜5.x)で追加される。実装が揃い次第、利用側が参照すべき
主要な公開シンボル(``run_scope``・``main`` 等)をここへ再公開する。
"""

__all__: list[str] = []
