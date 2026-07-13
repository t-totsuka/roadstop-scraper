# Requirements Document

## Project Description (Input)
道の駅スクレイピング機能・SA/PAスクレイピング機能の双方から利用される、HTTP取得・HTMLパースの共通エンジン。BeautifulSoup/Scrapyを用いたページ取得とパース処理の抽象化、リトライ・タイムアウト処理、対象サイトのHTML構造変化を検知した際のエラーハンドリングを提供する。
`02-common-infra`が提供するリクエスト頻度制御・レジューム機能、ログ出力(`python_util.logging`)と連携し、`03-geojson-schema`で定義された形式に沿ったデータを後段に渡せるようにする。また、`03-geojson-schema`で調査された情報も参考にする。`.kiro/specs/03-geojson-schema/research.md`

## Introduction

本specは、道の駅スクレイピング機能(`05-michinoeki-scraping`)・SA/PAスクレイピング機能(`06-sapa-scraping`)の双方が共通で利用する、HTTP取得・HTMLパースのスクレイピングエンジンを整備する。対象URLからのコンテンツ取得(HTML・JSON)、タイムアウト・リトライを含む取得失敗時の回復処理、パース処理の抽象化、および対象サイトのHTML構造変化を検知した際のエラーハンドリングを対象とする。取得処理は`02-common-infra`のリクエスト頻度制御・レジューム機能・共通ロギングと連携し、抽出結果は後段が`03-geojson-schema`で定義されたスキーマへマッピングできる形式で受け渡す。

## Boundary Context (Optional)

- **In scope**: URLを指定したHTTPコンテンツ取得(HTML・JSON)、タイムアウト・リトライ処理、HTMLパースと要素抽出の抽象化、HTML構造変化の検知とエラー送出、`02-common-infra`(リクエスト頻度制御・レジューム・ロギング)との連携、抽出結果の構造化された受け渡し
- **Out of scope**: 個別サイト固有のURL構成・抽出ルールの実装(`05-michinoeki-scraping`、`06-sapa-scraping`)、GeoJSONスキーマの定義・検証・ファイル出力(`03-geojson-schema`)、リクエスト頻度制御・レジューム・ロギング機構そのものの実装(`02-common-infra`)、座標を取得できない情報源への代替手段の実装(ジオコーディング等。`06-sapa-scraping`で検討)
- **Adjacent expectations**: `05-michinoeki-scraping`・`06-sapa-scraping`は本specの取得・パース手段を利用してサイト固有の抽出ロジックを実装する。本specは`02-common-infra`のレート制限・レジューム・ロガーを内部で利用し、`03-geojson-schema`のFeature構築に必要な情報(名称・座標・付加情報等)を欠落なく受け渡せる形式を提供する

## Requirements

### Requirement 1: HTTPコンテンツ取得

**Objective:** 開発者として、URLを指定して対象サイトのコンテンツを取得する共通手段を利用したい、そうすることで各スクレイピング機能がHTTPアクセス処理を個別実装せず、一貫した方法でページを取得できるようにするため

#### Acceptance Criteria

1. When URLを指定してコンテンツ取得が要求される, the Scraping Engine shall 対象URLへHTTPリクエストを送信し、レスポンス本文を取得して返す
2. The Scraping Engine shall HTMLページに加えて、JSON形式のレスポンス(例: NEXCO西日本の施設一覧JSON)も取得できる
3. When HTTPリクエストを実行する, the Scraping Engine shall 実行前に`02-common-infra`のリクエスト頻度制御を適用し、設定された最小待機時間を遵守する
4. When コンテンツ取得が成功する, the Scraping Engine shall 取得したレスポンス本文を文字化けなくテキストとして扱えるよう、レスポンスの文字エンコーディングを解決する
5. If HTTPレスポンスのステータスコードがエラー(4xx・5xx)である場合, then the Scraping Engine shall 取得失敗として扱い、対象URLとステータスコードを含む情報を呼び出し側へ伝える

### Requirement 2: タイムアウト・リトライ処理

**Objective:** 開発者として、一時的な通信障害に対する自動リトライと応答遅延に対するタイムアウトを共通処理として利用したい、そうすることで長時間のバッチ実行中に一時的な障害で処理全体が失敗しないようにするため

#### Acceptance Criteria

1. The Scraping Engine shall HTTPリクエストに設定可能なタイムアウト時間を適用する
2. If リクエストがタイムアウトまたはネットワークエラーにより失敗した場合, then the Scraping Engine shall 設定された最大回数を上限としてリトライする
3. If HTTPレスポンスがサーバエラー(5xx)である場合, then the Scraping Engine shall 一時的な失敗とみなしリトライの対象とする
4. If HTTPレスポンスがクライアントエラー(4xx)である場合, then the Scraping Engine shall リトライせずに取得失敗として確定させる
5. When リトライを実行する, the Scraping Engine shall 再送前に設定された待機時間を空け、対象サーバへ連続して負荷をかけない
6. If 最大リトライ回数に達しても取得が成功しない場合, then the Scraping Engine shall 対象URL・失敗理由を含むエラーを送出する
7. The Scraping Engine shall リトライの最大回数・リトライ時の待機時間・タイムアウト時間を、コードを変更せずに`pyproject.toml`の設定で外部から変更できるようにする
8. If `pyproject.toml`に該当する設定が存在しない場合, then the Scraping Engine shall あらかじめ定められた既定値で動作する

### Requirement 3: HTMLパースと要素抽出の抽象化

**Objective:** 開発者として、取得したHTMLから要素を抽出する共通のパース手段を利用したい、そうすることで各スクレイピング機能がパースライブラリの実装詳細に依存せず、サイト固有の抽出ルールの記述に集中できるようにするため

#### Acceptance Criteria

1. When 取得したHTMLのパースが要求される, the Scraping Engine shall HTMLを解析し、要素抽出が可能なパース結果を返す
2. The Scraping Engine shall セレクタ等の指定により、パース結果から要素・属性値・テキストを抽出する共通手段を提供する
3. The Scraping Engine shall パースライブラリ(BeautifulSoup等)の実装詳細を呼び出し側へ露出させないインタフェースを提供する
4. If パース不能な不正コンテンツが与えられた場合, then the Scraping Engine shall 対象URLを特定できる情報を含むエラーを送出する

### Requirement 4: HTML構造変化の検知とエラーハンドリング

**Objective:** 開発者として、対象サイトのHTML構造が変化して期待する要素を抽出できない事態を明確なエラーとして検知したい、そうすることで構造変化に起因する欠損データを黙って出力せず、抽出ルールの修正が必要であることを速やかに把握できるようにするため

#### Acceptance Criteria

1. If 抽出必須として指定された要素がパース結果から取得できない場合, then the Scraping Engine shall HTML構造変化を示す専用のエラーとして送出する
2. When HTML構造変化のエラーを送出する, the Scraping Engine shall 対象URLと取得できなかった要素の特定情報(セレクタ等)をエラーに含める
3. When HTML構造変化を検知する, the Scraping Engine shall 該当イベントを警告以上のレベルでログに記録する
4. The Scraping Engine shall HTML構造変化のエラーを呼び出し側が捕捉・判別できる独自の例外型として定義し、呼び出し側が処理の継続・中断を選択できるようにする

### Requirement 5: 共通基盤(ロギング・レジューム)との連携

**Objective:** 開発者として、スクレイピングエンジンの動作状況を共通ロギングで記録し、取得処理をレジューム機能と組み合わせて利用したい、そうすることで長時間のバッチ実行の進捗・障害を追跡でき、中断後も続きから再開できるようにするため

#### Acceptance Criteria

1. The Scraping Engine shall 動作ログを`python_util.logging`の`get_logger()`から取得した共通ロガーで出力する
2. When HTTP取得の開始・成功・失敗・リトライが発生する, the Scraping Engine shall 対象URLを含む該当イベントをログに記録する
3. When 複数URLの連続取得が要求される, the Scraping Engine shall `02-common-infra`のレジューム機能と連携し、処理済みとして記録されたURLの再取得をスキップできる手段を提供する
4. When URLの取得・処理が完了する, the Scraping Engine shall 該当URLを処理済みとしてレジューム状態に記録できる手段を提供する

### Requirement 6: 抽出結果の構造化された受け渡し

**Objective:** 開発者として、スクレイピングエンジンの抽出結果を構造化された形式で受け取りたい、そうすることで後段の処理が`03-geojson-schema`で定義されたスキーマ(名称・座標・付加情報等)へのマッピングを一貫した方法で実装できるようにするため

#### Acceptance Criteria

1. When 要素の抽出が完了する, the Scraping Engine shall 抽出結果を、呼び出し側が`03-geojson-schema`のFeature構築(名称・緯度経度・付加情報等へのマッピング)に利用できる構造化された形式で返す
2. The Scraping Engine shall 抽出結果に取得元URL(`source_url`として利用可能な情報)を対応付けられるようにする
3. If 任意項目の抽出結果が存在しない場合, then the Scraping Engine shall 該当項目を欠損として判別可能な形で返し、処理を中断しない
