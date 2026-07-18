# Requirements Document

## Project Description (Input)
全国の道の駅の位置情報・名称・付加情報を対象Webサイトからスクレイピングし、都道府県単位で分割したGeoJSONファイル(`geo-json/(都道府県番号2桁)_(都道府県名ローマ字)_michinoeki.geojson`)として保存する機能。サードパーティサーバへの負荷を避けるリクエスト頻度制御と、中断・再開が可能なレジューム機能を備える。スクレイピング結果は`geo-json/index.json`に更新日時とファイルパスを登録して管理する。動作ログは`python_util.logging`を用いて記録する。

## Introduction

本specは、全国の道の駅の位置情報・名称・付加情報を対象Webサイトからスクレイピングし、都道府県単位で分割したGeoJSONファイルとして`geo-json/`配下へ出力する機能を定義する。対象は道の駅一覧の収集、個々の道の駅詳細ページからの情報抽出、都道府県単位でのGeoJSON出力と`geo-json/index.json`の更新、実行対象範囲(全国・地方・都道府県)の指定、個々の道の駅の抽出失敗時のスキップと継続処理、対象サイト側で廃止された道の駅の扱い、および中断・再開(レジューム)である。本機能は`04-scraping-engine`が提供する取得・パース手段、`03-geojson-schema`が定義するGeoJSON出力スキーマ・検証・書き込み手段、`02-common-infra`が提供するレート制限・レジューム永続化・`index.json`管理・共通ロギング基盤を利用し、道の駅アプリ等の消費側が単一スキーマでデータを扱えるようにする。

## Boundary Context (Optional)

- **In scope**: 対象サイトからの道の駅一覧・詳細情報の収集、全国／地方(北海道・東北・関東・中部・近畿・四国・中国・九州沖縄)／都道府県単位での実行対象範囲の指定、抽出情報の道の駅向けGeoJSONプロパティへのマッピング、都道府県単位でのGeoJSONファイル出力と`index.json`更新、個々の道の駅の抽出失敗時のスキップと処理継続、対象サイト側で一覧から消失した道の駅の削除状態管理(削除フラグ・最終確認日時・1年経過後の完全除去)、実行の中断・再開(レジューム)
- **Out of scope**: HTTP取得・HTMLパースの共通処理そのもの(`04-scraping-engine`が所有)、GeoJSONのFeature構造・座標系・命名規則・出力前検証・書き込み処理そのもの(`03-geojson-schema`が所有)、`geo-json/index.json`の読み込み・更新・保存機構そのもの、リクエスト頻度制御・レジューム永続化機構そのもの(いずれも`02-common-infra`が所有し、`04-scraping-engine`経由で利用する)、SA/PAのスクレイピング(`06-sapa-scraping`)、道の駅データの手動編集・上書き手段
- **Adjacent expectations**: 本機能は、削除状態(削除フラグ・最終確認日時)を道の駅単位のGeoJSONプロパティとして保持できることを前提とする。現時点の`03-geojson-schema`の`FacilityProperties`にはこれに相当する項目が存在しないため、本機能の実装に先立って`03-geojson-schema`側でのスキーマ拡張(前提作業)が必要になる。本機能は`04-scraping-engine`が提供する取得・パース・レジューム手段、および`02-common-infra`が提供するレート制限・`index.json`管理・共通ロギング基盤をそのまま利用し、これらの内部実装は変更しない。

## Requirements

### Requirement 1: 実行対象範囲の指定

**Objective:** 運用者として、全国・地方・都道府県のいずれかの単位でスクレイピング対象範囲を指定して実行したい、そうすることで初回の全国一括収集だけでなく、特定地域の再取得や部分実行を柔軟に行えるようにするため

#### Acceptance Criteria

1. Where 運用者が対象範囲を指定せずに実行する, the Michinoeki Scraper shall 全47都道府県を対象としてスクレイピングを実行する
2. Where 運用者が地方区分(北海道・東北・関東・中部・近畿・四国・中国・九州沖縄のいずれか)を指定する, the Michinoeki Scraper shall 指定された地方に属する都道府県のみを対象としてスクレイピングを実行する
3. Where 運用者が特定の都道府県を指定する, the Michinoeki Scraper shall 指定された都道府県のみを対象としてスクレイピングを実行する
4. If 指定された地方区分または都道府県が実在しない値である場合, then the Michinoeki Scraper shall エラーを報告し、スクレイピングを開始しない

### Requirement 2: 道の駅一覧の収集

**Objective:** 開発者として、都道府県ごとに登録されている道の駅の一覧を対象サイトから収集したい、そうすることで個々の道の駅詳細ページの取得対象を過不足なく特定できるようにするため

#### Acceptance Criteria

1. When 対象都道府県のスクレイピングが開始される, the Michinoeki Scraper shall 対象サイトから当該都道府県に登録されている道の駅の一覧を取得する
2. The Michinoeki Scraper shall 取得した一覧から、個々の道の駅の詳細ページを特定できる情報を得る
3. If 対象都道府県の一覧取得に失敗した場合, then the Michinoeki Scraper shall 当該都道府県のスクレイピングを中断してエラーを報告し、他の対象都道府県の処理は継続する

### Requirement 3: 道の駅詳細情報の抽出

**Objective:** 開発者として、個々の道の駅詳細ページから名称・位置情報・付加情報を抽出したい、そうすることで消費側アプリケーションが必要とする情報を単一のGeoJSONデータとして提供できるようにするため

#### Acceptance Criteria

1. When 個々の道の駅の詳細ページの処理が実行される, the Michinoeki Scraper shall 名称・住所(郵便番号を含む)・電話番号・営業時間・駐車場台数(大型・普通車・身障者用)・施設ホームページ(最大2件)・マップコード・緯度経度を抽出する
2. The Michinoeki Scraper shall 抽出した施設設備・サービスの情報を文字列の配列として記録する
3. The Michinoeki Scraper shall 抽出した情報を、都道府県番号・都道府県名・施設種別(道の駅)とあわせて道の駅向けのGeoJSONプロパティ形式に変換する
4. If 道の駅の緯度経度を解釈できない場合, then the Michinoeki Scraper shall 当該道の駅を抽出失敗として扱う

### Requirement 4: 抽出失敗時のエラーハンドリング

**Objective:** 運用者として、個々の道の駅ページでの抽出失敗が発生してもバッチ処理全体を止めたくない、そうすることで一部ページの構造変化やデータ欠落が全体の収集を妨げないようにするため

#### Acceptance Criteria

1. If 個々の道の駅詳細ページの抽出において必須項目(名称・座標等)が取得できない場合, then the Michinoeki Scraper shall 当該道の駅をスキップし、対象URLを含む警告以上のレベルのログを記録する
2. When 道の駅がスキップされる, the Michinoeki Scraper shall 当該都道府県内の他の道の駅、および他の対象都道府県のスクレイピング処理を継続する
3. The Michinoeki Scraper shall 都道府県単位でのスキップ件数を運用者が確認できる形で記録する

### Requirement 5: 都道府県単位のGeoJSON出力

**Objective:** 開発者として、収集した道の駅データを都道府県単位で分割したGeoJSONファイルとして永続化したい、そうすることでファイルサイズの肥大化を防ぎつつ消費側アプリケーションが都道府県単位でデータを取得できるようにするため

#### Acceptance Criteria

1. When 1つの都道府県の道の駅データ収集が完了する, the Michinoeki Scraper shall 当該都道府県・施設種別(道の駅)に対応する命名規則のGeoJSONファイルへ出力する
2. If 出力対象データがGeoJSON出力スキーマの検証に違反する場合, then the Michinoeki Scraper shall 当該都道府県のファイル出力を中断し、違反内容を報告する
3. When 都道府県のGeoJSONファイル出力が正常に完了する, the Michinoeki Scraper shall `geo-json/index.json`の該当ファイルパスと更新日時を最新の内容に更新する

### Requirement 6: 実行の中断・再開(レジューム)

**Objective:** 運用者として、長時間・大量ページのスクレイピングが途中で中断しても再実行時に続きから処理したい、そうすることで中断のたびに全件を再取得する無駄を避けられるようにするため

#### Acceptance Criteria

1. While 前回の実行が中断された状態から再実行される, the Michinoeki Scraper shall 前回処理済みと記録された道の駅の再取得をスキップする
2. When 個々の道の駅の処理(詳細ページ取得・抽出)が完了する, the Michinoeki Scraper shall 当該道の駅を処理済みとして記録する
3. When 指定された対象範囲(全国・地方・都道府県)のスクレイピングが正常に完了する, the Michinoeki Scraper shall レジューム状態をクリアする

### Requirement 7: リクエスト頻度制御

**Objective:** 運用者として、対象サイトへの負荷を抑えたリクエスト間隔でスクレイピングを実行したい、そうすることでサードパーティサーバへの過度な負荷を避けられるようにするため

#### Acceptance Criteria

1. The Michinoeki Scraper shall 対象サイトへのすべてのHTTPリクエストに、設定された最小リクエスト間隔を適用する

### Requirement 8: 廃止された道の駅の扱い

**Objective:** 開発者として、対象サイトの一覧から消失した道の駅のデータを即座に削除せず、削除状態を明示した上で一定期間保持したい、そうすることで消費側アプリケーションが「一時的にサイト側から確認できない」と「恒久的に廃止された」を区別でき、かつデータが無期限に肥大化しないようにするため

#### Acceptance Criteria

1. When 対象サイトの一覧に道の駅が存在することが確認される, the Michinoeki Scraper shall 当該道の駅の最終確認日時を更新する
2. If 都道府県の全件スクレイピングにおいて、既にGeoJSONへ出力済みの道の駅が対象サイトの一覧に存在しなくなっている場合, then the Michinoeki Scraper shall 当該道の駅のデータを削除せず、削除状態であることを示す情報を付与して出力を継続する
3. If 削除状態の道の駅が対象サイトの一覧に再び存在することを確認した場合, then the Michinoeki Scraper shall 削除状態を解除し、最新の情報で更新する
4. If 削除状態の道の駅について最終確認日時から1年が経過した場合, then the Michinoeki Scraper shall 当該道の駅のデータをGeoJSON出力から完全に除去する
5. Where 都道府県を指定した部分実行が行われる場合, the Michinoeki Scraper shall 削除状態の判定・更新を、指定範囲に含まれる都道府県内の道の駅に限定して適用する

### Requirement 9: 動作ログの記録

**Objective:** 運用者として、スクレイピングの進捗と発生した問題を共通ログで追跡したい、そうすることでバッチ実行の状況把握と問題発生時の原因調査を行えるようにするため

#### Acceptance Criteria

1. The Michinoeki Scraper shall 実行開始・完了、対象都道府県ごとの取得件数、スキップした道の駅件数、削除状態へ移行・解除・完全除去した道の駅件数を共通ロギング基盤で記録する
2. When スクレイピング処理中にエラーが発生する, the Michinoeki Scraper shall 対象URL・都道府県・エラー内容を含む情報をログに記録する
