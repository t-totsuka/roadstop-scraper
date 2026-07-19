"""サイト単位の収集ループと部分結果の逐次永続化(雛形)。

1サイト分の一覧→詳細→座標解決→Feature化の収集ループ(``collect_site``)
と、実行横断の部分結果キャッシュ(``SapaPartialStore``)を提供するモジュール
(design.md「sapa.collector」節参照)。実装はタスク4.1・4.2で行う。
"""
