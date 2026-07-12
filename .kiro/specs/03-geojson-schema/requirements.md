# Requirements Document

## Project Description (Input)
道の駅・SA/PA双方のスクレイピング結果が共通で従うGeoJSON出力スキーマを定義する機能。Feature Collectionのプロパティ項目(名称、住所、緯度経度、付加情報等)、座標系(WGS84/EPSG:4326)、`geo-json/(都道府県番号2桁)_(都道府県名ローマ字)_(michinoeki|sapa).geojson`という命名規則、および出力前のバリデーションルールを定義する。あわせて`geo-json/index.json`(各GeoJSONファイルの`path`と`updated_at`を保持する管理ファイル)のスキーマとの整合性も定義する。

## Introduction

本specは、道の駅スクレイピング機能(`05-michinoeki-scraping`)・SA/PAスクレイピング機能(`06-sapa-scraping`)の双方のスクレイピング結果が共通で従うGeoJSON出力スキーマを定義する。FeatureCollectionの構造とプロパティ項目、座標系(WGS84/EPSG:4326)、都道府県単位の出力ファイル命名規則、出力前のバリデーションルール、および`geo-json/index.json`のスキーマとの整合性を対象とする。これにより、消費側アプリケーション(道の駅アプリ等)が施設種別を問わず単一のスキーマでデータを扱えるようにする。

## Boundary Context (Optional)

- **In scope**: GeoJSON FeatureCollectionの構造・プロパティ項目の定義、座標系(WGS84/EPSG:4326)の規定、出力ファイル命名規則の定義、出力前バリデーションルールの定義と検証手段の提供、`geo-json/index.json`スキーマとの整合性ルールの定義
- **Out of scope**: `index.json`の読み書き・更新処理そのもの(`02-common-infra`で整備済み)、HTTP取得・HTMLパースの共通エンジン(`04-scraping-engine`)、個別サイトからのデータ収集ロジック(`05-michinoeki-scraping`、`06-sapa-scraping`)
- **Adjacent expectations**: `05-michinoeki-scraping`・`06-sapa-scraping`は本specが定義するスキーマ・命名規則に適合するGeoJSONを生成し、出力前に本specのバリデーションを通過させる。`02-common-infra`の`index.json`更新ロジックには、本specの命名規則に適合する`path`が登録される

## Requirements

### Requirement 1: GeoJSON FeatureCollection構造の定義

**Objective:** 開発者として、道の駅・SA/PA双方の出力が従う共通のFeatureCollection構造を定義したい、そうすることで消費側アプリケーションが施設種別を問わず単一の構造でデータを解釈できるようにするため

#### Acceptance Criteria

1. The GeoJSON Schema shall 出力ファイルのルート要素をRFC 7946に準拠した`FeatureCollection`型として定義する
2. The GeoJSON Schema shall 1つの施設(道の駅またはSA/PA)を1つの`Feature`として表現するよう定義する
3. The GeoJSON Schema shall 各Featureの`geometry`を`Point`型として定義する
4. The GeoJSON Schema shall 道の駅・SA/PAの双方に同一のFeature構造(同一のプロパティスキーマ)を適用する

### Requirement 2: Featureプロパティ項目の定義

**Objective:** 開発者として、施設の名称・住所・付加情報を一貫した項目名・型で保持するプロパティスキーマを定義したい、そうすることで道の駅・SA/PAのスクレイピング結果を同じ項目定義で参照・検証できるようにするため

#### Acceptance Criteria

1. The GeoJSON Schema shall 各Featureの`properties`に施設名称を必須項目として定義する
2. The GeoJSON Schema shall 各Featureの`properties`に住所(郵便番号を含む)を項目として定義する
3. The GeoJSON Schema shall 各Featureの`properties`に施設種別(道の駅・SA/PAの区分)を必須項目として定義する
4. The GeoJSON Schema shall 各Featureの`properties`に施設が所在する都道府県の情報(都道府県番号・都道府県名)を定義する
5. The GeoJSON Schema shall 共通の付加情報として、電話番号、営業時間、駐車場台数(大型・普通車・身障者用)、施設ホームページURL、情報源URL(スクレイピング元ページのURL)を任意項目として定義する
6. The GeoJSON Schema shall 施設設備・サービス(レストラン、温泉施設、EV充電、ドッグラン等)を文字列配列として格納する任意項目を定義する(情報源ごとに語彙・粒度が異なるため、固定のブール項目としては定義しない)
7. Where 施設種別がSA/PAである場合, the GeoJSON Schema shall 路線名、上り/下りの区分、方面を格納できる任意項目を定義する
8. Where 施設種別が道の駅である場合, the GeoJSON Schema shall マップコードを格納できる任意項目を定義する
9. Where 任意項目に該当する値がスクレイピング結果に存在しない場合, the GeoJSON Schema shall 該当項目の省略または`null`値を許容する

### Requirement 3: 座標系と座標値の定義

**Objective:** 開発者として、全出力ファイルで統一された座標系と座標表現を定義したい、そうすることで消費側アプリケーションが座標変換なしに位置情報を利用できるようにするため

#### Acceptance Criteria

1. The GeoJSON Schema shall 座標系をWGS84(EPSG:4326)として定義する
2. The GeoJSON Schema shall `geometry.coordinates`を[経度, 緯度]の順序で記録するよう定義する
3. The GeoJSON Schema shall 緯度を-90以上90以下、経度を-180以上180以下の数値として定義する

### Requirement 4: 出力ファイル命名規則の定義

**Objective:** 開発者として、都道府県単位で分割された出力ファイルの命名規則を定義したい、そうすることで分割ファイルを一貫した規則で命名し、ファイルサイズの肥大化を防げるようにするため(ファイル名はあくまで分割の単位であり、名前自体に内容の契約を持たせない)

#### Acceptance Criteria

1. The GeoJSON Schema shall 出力ファイル名を`(都道府県番号2桁)_(都道府県名ローマ字)_(michinoeki|sapa).geojson`の形式として定義する
2. The GeoJSON Schema shall 都道府県番号を全国地方公共団体コードに基づく`01`〜`47`のゼロ埋め2桁として定義する
3. The GeoJSON Schema shall 都道府県名を小文字ローマ字表記として定義する(例: `01_hokkaido_michinoeki.geojson`)
4. The GeoJSON Schema shall 施設種別の表記を道の駅は`michinoeki`、SA/PAは`sapa`の2値に限定する
5. The GeoJSON Schema shall 出力先ディレクトリを`geo-json/`として定義する
6. The GeoJSON Schema shall 47都道府県すべてについて都道府県番号と都道府県名ローマ字の対応を参照できる手段を提供する

### Requirement 5: 出力前バリデーション

**Objective:** 開発者として、GeoJSONファイルの書き出し前にスキーマ違反を検出したい、そうすることでスキーマに適合しない不正なデータが`geo-json/`配下へ永続化されることを防げるようにするため

#### Acceptance Criteria

1. When GeoJSONデータの出力が要求される, the GeoJSON Schema shall ファイル書き込み前にRequirement 1〜3で定義したスキーマへの適合性を検証する
2. If 必須項目(施設名称・施設種別等)が欠落したFeatureが存在する場合, then the GeoJSON Schema shall 対象のFeatureと違反項目を特定できる検証エラーを報告する
3. If 座標値が定義された範囲外、または[経度, 緯度]として解釈できない形式である場合, then the GeoJSON Schema shall 検証エラーを報告する
4. If 出力先のファイル名がRequirement 4の命名規則に適合しない場合, then the GeoJSON Schema shall 検証エラーを報告する
5. If 検証エラーが1件以上存在する場合, then the GeoJSON Schema shall 該当ファイルの出力を中断する
6. When すべての検証に合格する, the GeoJSON Schema shall 出力処理の続行を許可する

### Requirement 6: geo-json/index.jsonスキーマとの整合性

**Objective:** 開発者として、GeoJSON出力スキーマと`index.json`の管理項目の整合性ルールを定義したい、そうすることで`index.json`が参照するファイル一覧と実際の出力ファイルが常に矛盾なく対応するようにするため

#### Acceptance Criteria

1. The GeoJSON Schema shall `index.json`の`path`項目を`geo-json/`ディレクトリからの相対ファイル名として定義する
2. The GeoJSON Schema shall `index.json`の`path`項目がRequirement 4の命名規則に適合することを整合性ルールとして定義する
3. The GeoJSON Schema shall `index.json`の`updated_at`項目をISO 8601形式のタイムスタンプとして定義する(`02-common-infra`の記録形式と一致させる)
4. If `index.json`の整合性検証が要求され、命名規則に適合しない`path`のエントリが存在した場合, then the GeoJSON Schema shall 検証エラーを報告する
