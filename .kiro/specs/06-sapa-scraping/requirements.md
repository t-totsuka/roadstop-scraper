# Requirements Document

## Project Description (Input)
全国の高速道路SA(サービスエリア)・PA(パーキングエリア)の位置情報・名称・付加情報を対象Webサイトからスクレイピングし、都道府県単位で分割したGeoJSONファイル(`geo-json/(都道府県番号2桁)_(都道府県名ローマ字)_sapa.geojson`)として保存する機能。サードパーティサーバへの負荷を避けるリクエスト頻度制御と、中断・再開が可能なレジューム機能を備える。スクレイピング結果は`geo-json/index.json`に更新日時とファイルパスを登録して管理する。動作ログは`python_util.logging`を用いて記録する。

## Introduction

本specは、全国の高速道路SA(サービスエリア)・PA(パーキングエリア)の位置情報・名称・付加情報を対象Webサイトからスクレイピングし、都道府県単位で分割したGeoJSONファイルとして`geo-json/`配下へ出力する機能を定義する。対象はSA/PA一覧の収集、個々のSA/PA詳細ページからの情報抽出(路線名・上り/下り区分を含む)、対象サイトから座標を直接取得できない施設への座標補完、都道府県単位でのGeoJSON出力と`geo-json/index.json`の更新、実行対象範囲(全国・地方・都道府県)の指定、個々のSA/PAの抽出失敗時のスキップと継続処理、対象サイト側で廃止されたSA/PAの扱い、および中断・再開(レジューム)である。本機能は`04-scraping-engine`が提供する取得・パース手段、`03-geojson-schema`が定義するGeoJSON出力スキーマ・検証・書き込み手段、`02-common-infra`が提供するレート制限・レジューム永続化・`index.json`管理・共通ロギング基盤を利用し、道の駅アプリ等の消費側が道の駅と同一スキーマでSA/PAデータを扱えるようにする。

## Boundary Context (Optional)

- **In scope**: 対象サイトからのSA/PA一覧・詳細情報の収集、全国/地方(北海道・東北・関東・中部・近畿・四国・中国・九州沖縄)/都道府県単位での実行対象範囲の指定、対象サイトから座標を直接取得できない施設に対する住所等の取得済み情報からの座標補完、抽出情報のSA/PA向けGeoJSONプロパティ(路線名・上り/下り区分・方面を含む)へのマッピング、都道府県単位でのGeoJSONファイル出力と`index.json`更新、個々のSA/PAの抽出失敗時のスキップと処理継続、対象サイト側で一覧から消失したSA/PAの削除状態管理(削除フラグ・最終確認日時・1年経過後の完全除去)、実行の中断・再開(レジューム)
- **Out of scope**: HTTP取得・HTMLパースの共通処理そのもの(`04-scraping-engine`が所有)、GeoJSONのFeature構造・座標系・命名規則・出力前検証・書き込み処理そのもの(`03-geojson-schema`が所有)、`geo-json/index.json`の読み込み・更新・保存機構そのもの、リクエスト頻度制御・レジューム永続化機構そのもの(いずれも`02-common-infra`が所有し、`04-scraping-engine`経由で利用する)、道の駅のスクレイピング(`05-michinoeki-scraping`)、SA/PAデータの手動編集・上書き手段
- **Adjacent expectations**: 本機能は、GeoJSON出力スキーマがSA/PA固有項目(路線名・上り/下り区分・方面)および削除状態(削除フラグ・最終確認日時)を施設単位のプロパティとして保持できることを前提とする。これらは`03-geojson-schema`に既に定義済みであり、本機能のための追加のスキーマ拡張は前提としない。本機能は`04-scraping-engine`が提供する取得・パース手段、および`02-common-infra`が提供するレート制限・`index.json`管理・共通ロギング基盤をそのまま利用し、これらの内部実装は変更しない。座標補完の具体的な導出手段(外部情報源の利用有無を含む)は設計フェーズで決定する。

## Requirements

### Requirement 1: 実行対象範囲の指定

**Objective:** 運用者として、全国・地方・都道府県のいずれかの単位でスクレイピング対象範囲を指定して実行したい、そうすることで初回の全国一括収集だけでなく、特定地域の再取得や部分実行を柔軟に行えるようにするため

#### Acceptance Criteria

1. Where 運用者が対象範囲を指定せずに実行する, the SAPA Scraper shall 全47都道府県を対象としてスクレイピングを実行する
2. Where 運用者が地方区分(北海道・東北・関東・中部・近畿・四国・中国・九州沖縄のいずれか)を指定する, the SAPA Scraper shall 指定された地方に属する都道府県のみを対象としてスクレイピングを実行する
3. Where 運用者が特定の都道府県を指定する, the SAPA Scraper shall 指定された都道府県のみを対象としてスクレイピングを実行する
4. If 指定された地方区分または都道府県が実在しない値である場合, then the SAPA Scraper shall エラーを報告し、スクレイピングを開始しない

### Requirement 2: SA/PA一覧の収集

**Objective:** 開発者として、対象範囲の都道府県に所在するSA/PAの一覧を対象サイトから収集したい、そうすることで個々のSA/PA詳細ページの取得対象を過不足なく特定できるようにするため

#### Acceptance Criteria

1. When 指定された対象範囲のスクレイピングが開始される, the SAPA Scraper shall 対象サイトから、対象範囲に含まれる都道府県に所在するSA/PAの一覧(上り線・下り線の施設を含む)を取得する
2. The SAPA Scraper shall 取得した一覧から、個々のSA/PAの詳細ページを特定できる情報を得る
3. If 一覧の取得に失敗した場合, then the SAPA Scraper shall 失敗した範囲の処理を中断してエラーを報告し、他の対象の処理は継続する

### Requirement 3: SA/PA詳細情報の抽出

**Objective:** 開発者として、個々のSA/PA詳細ページから名称・路線名・上り/下り区分・位置情報・付加情報を抽出したい、そうすることで消費側アプリケーションが必要とする情報を道の駅と同一スキーマのGeoJSONデータとして提供できるようにするため

#### Acceptance Criteria

1. When 個々のSA/PAの詳細ページの処理が実行される, the SAPA Scraper shall 名称・路線名・緯度経度を抽出する
2. Where 対象サイトで上り線・下り線の区別が提供されている場合, the SAPA Scraper shall 上り/下り区分を記録し、上り線・下り線それぞれの施設を別々のデータとして扱う
3. The SAPA Scraper shall 住所(郵便番号を含む)・電話番号・営業時間・駐車場台数(大型・普通車・身障者用)・施設ホームページ・方面を、対象サイトで提供されている場合に抽出して記録する
4. The SAPA Scraper shall 抽出した施設設備・サービスの情報を文字列の配列として記録する
5. The SAPA Scraper shall 抽出した情報を、都道府県番号・都道府県名・施設種別(SA/PA)とあわせてSA/PA向けのGeoJSONプロパティ形式に変換する
6. If SA/PAの所在都道府県を特定できない場合, then the SAPA Scraper shall 当該SA/PAを抽出失敗として扱う

### Requirement 4: 座標の取得と補完

**Objective:** 開発者として、対象サイトから緯度経度を直接取得できないSA/PAについても住所等の取得済み情報から座標を補完して収集したい、そうすることでデータセットの網羅性を確保し、消費側アプリケーションが全国のSA/PAを地図上で扱えるようにするため

#### Acceptance Criteria

1. When 対象サイトから緯度経度を直接取得できる, the SAPA Scraper shall 取得した緯度経度を当該SA/PAの座標として記録する
2. If 対象サイトから緯度経度を直接取得できない場合, then the SAPA Scraper shall 住所等の取得済み情報から座標を導出して補完する
3. If 座標の直接取得も補完もできない場合, then the SAPA Scraper shall 当該SA/PAを抽出失敗として扱う
4. When 座標を補完によって取得した場合, the SAPA Scraper shall 補完により座標を得たことを運用者が確認できる形で記録する

### Requirement 5: 抽出失敗時のエラーハンドリング

**Objective:** 運用者として、個々のSA/PAページでの抽出失敗が発生してもバッチ処理全体を止めたくない、そうすることで一部ページの構造変化やデータ欠落が全体の収集を妨げないようにするため

#### Acceptance Criteria

1. If 個々のSA/PA詳細ページの抽出において必須項目(名称・路線名・座標等)が取得できない場合, then the SAPA Scraper shall 当該SA/PAをスキップし、対象URLを含む警告以上のレベルのログを記録する
2. When SA/PAがスキップされる, the SAPA Scraper shall 他のSA/PA、および他の対象都道府県のスクレイピング処理を継続する
3. The SAPA Scraper shall 都道府県単位でのスキップ件数を運用者が確認できる形で記録する

### Requirement 6: 都道府県単位のGeoJSON出力

**Objective:** 開発者として、収集したSA/PAデータを都道府県単位で分割したGeoJSONファイルとして永続化したい、そうすることでファイルサイズの肥大化を防ぎつつ消費側アプリケーションが都道府県単位でデータを取得できるようにするため

#### Acceptance Criteria

1. When 1つの都道府県のSA/PAデータ収集が完了する, the SAPA Scraper shall 当該都道府県・施設種別(SA/PA)に対応する命名規則のGeoJSONファイルへ出力する
2. If 出力対象データがGeoJSON出力スキーマの検証に違反する場合, then the SAPA Scraper shall 当該都道府県のファイル出力を中断し、違反内容を報告する
3. When 都道府県のGeoJSONファイル出力が正常に完了する, the SAPA Scraper shall `geo-json/index.json`の該当ファイルパスと更新日時を最新の内容に更新する

### Requirement 7: 実行の中断・再開(レジューム)

**Objective:** 運用者として、長時間・大量ページのスクレイピングが途中で中断しても再実行時に続きから処理したい、そうすることで中断のたびに全件を再取得する無駄を避けられるようにするため

#### Acceptance Criteria

1. While 前回の実行が中断された状態から再実行される, the SAPA Scraper shall 前回処理済みと記録されたSA/PAの再取得をスキップする
2. When 個々のSA/PAの処理(詳細ページ取得・抽出)が完了する, the SAPA Scraper shall 当該SA/PAを処理済みとして記録する
3. When 指定された対象範囲(全国・地方・都道府県)のスクレイピングが正常に完了する, the SAPA Scraper shall レジューム状態をクリアする

### Requirement 8: リクエスト頻度制御

**Objective:** 運用者として、対象サイトへの負荷を抑えたリクエスト間隔でスクレイピングを実行したい、そうすることでサードパーティサーバへの過度な負荷を避けられるようにするため

#### Acceptance Criteria

1. The SAPA Scraper shall 対象サイトへのすべてのHTTPリクエストに、設定された最小リクエスト間隔を適用する

### Requirement 9: 廃止されたSA/PAの扱い

**Objective:** 開発者として、対象サイトの一覧から消失したSA/PAのデータを即座に削除せず、削除状態を明示した上で一定期間保持したい、そうすることで消費側アプリケーションが「一時的にサイト側から確認できない」と「恒久的に廃止された」を区別でき、かつデータが無期限に肥大化しないようにするため

#### Acceptance Criteria

1. When 対象サイトの一覧にSA/PAが存在することが確認される, the SAPA Scraper shall 当該SA/PAの最終確認日時を更新する
2. If 都道府県の全件スクレイピングにおいて、既にGeoJSONへ出力済みのSA/PAが対象サイトの一覧に存在しなくなっている場合, then the SAPA Scraper shall 当該SA/PAのデータを削除せず、削除状態であることを示す情報を付与して出力を継続する
3. If 削除状態のSA/PAが対象サイトの一覧に再び存在することを確認した場合, then the SAPA Scraper shall 削除状態を解除し、最新の情報で更新する
4. If 削除状態のSA/PAについて最終確認日時から1年が経過した場合, then the SAPA Scraper shall 当該SA/PAのデータをGeoJSON出力から完全に除去する
5. Where 都道府県を指定した部分実行が行われる場合, the SAPA Scraper shall 削除状態の判定・更新を、指定範囲に含まれる都道府県内のSA/PAに限定して適用する

### Requirement 10: 動作ログの記録

**Objective:** 運用者として、スクレイピングの進捗と発生した問題を共通ログで追跡したい、そうすることでバッチ実行の状況把握と問題発生時の原因調査を行えるようにするため

#### Acceptance Criteria

1. The SAPA Scraper shall 実行開始・完了、対象都道府県ごとの取得件数、スキップしたSA/PA件数、座標を補完したSA/PA件数、削除状態へ移行・解除・完全除去したSA/PA件数を共通ロギング基盤で記録する
2. When スクレイピング処理中にエラーが発生する, the SAPA Scraper shall 対象URL・都道府県・エラー内容を含む情報をログに記録する
