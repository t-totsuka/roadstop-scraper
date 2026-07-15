# roadstop-scraper

全国の道の駅、および高速道路のSA(サービスエリア)・PA(パーキングエリア)に関する位置情報・名称・付加情報を対象Webサイトからスクレイピングして収集し、GeoJSON形式で保存するデータ収集アプリケーション。

## 概要

- 道の駅・SA/PAの位置情報(緯度経度)、名称、付加情報のスクレイピング
- 収集結果のGeoJSON形式での永続化(都道府県単位でファイル分割)
- 中断・再開可能なレジューム機能
- サードパーティサーバへの負荷を抑えるリクエスト頻度制御(レート制限)
- HTTP取得・HTMLパース・リトライ/レート制限・構造変化検知を提供するスクレイピングエンジン(`scraping`パッケージ、道の駅/SA・PA個別スクレイパの共通基盤)

## セットアップ

```bash
pdm install
```

## 開発コマンド

```bash
# Lint
pdm run ruff check .

# テスト(HTMLカバレッジレポートを report/ に出力)
pdm run pytest
```

## ディレクトリ構成

```text
roadstop-scraper/
├── src/roadstop_scraper/   # アプリケーションソースコード
├── tests/                  # テストコード
├── geo-json/                # スクレイピング結果(GeoJSON)の出力先
└── report/                  # テストカバレッジレポート出力先(git管理対象外)
```

詳細な設計方針は `.kiro/steering/` を参照してください。
