# Requirements Document

## Project Description (Input)
全国の道の駅の位置情報・名称・付加情報を対象Webサイトからスクレイピングし、都道府県単位で分割したGeoJSONファイル(`geo-json/(都道府県番号2桁)_(都道府県名ローマ字)_michinoeki.geojson`)として保存する機能。サードパーティサーバへの負荷を避けるリクエスト頻度制御と、中断・再開が可能なレジューム機能を備える。スクレイピング結果は`geo-json/index.json`に更新日時とファイルパスを登録して管理する。動作ログは`python_util.logging`を用いて記録する。

## Requirements
<!-- Will be generated in /kiro-spec-requirements phase -->
