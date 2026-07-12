# Product Overview

全国の道の駅、および高速道路のSA(サービスエリア)・PA(パーキングエリア)に関する位置情報・名称・付加情報を、対象Webサイトからスクレイピングして収集し、GeoJSON形式で保存するデータ収集アプリケーション。

## Core Capabilities

- 道の駅・SA/PAの位置情報(緯度経度)、名称、付加情報のスクレイピング
- 収集結果のGeoJSON形式での永続化
- 中断・再開可能なレジューム機能(スクレイピング途中で停止しても再実行時に続きから処理できる)
- サードパーティサーバへの負荷を抑えるリクエスト頻度制御(レート制限)

## Target Use Cases

- 道の駅アプリ(`mitinoeki_app`など)へのマスターデータ供給
- 全国規模の道の駅・SA/PA位置情報を一括収集するバッチ処理

## Value Proposition

- 全国に散在する道の駅・SA/PA情報を単一のGeoJSONデータセットに集約する
- スクレイピング先サーバへの配慮(頻度制御・レジューム)を組み込みで備えた、倫理的で運用に強いデータ収集基盤

---

Focus on patterns and purpose, not exhaustive feature lists.
