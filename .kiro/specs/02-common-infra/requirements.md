# Requirements Document

## Project Description (Input)
道の駅スクレイピング機能・SA/PAスクレイピング機能の双方から共通で利用する基盤部分の機能。`python_util.logging`を用いた動作ログ出力の共通セットアップ、`geo-json/index.json`(各GeoJSONファイルの`path`と`updated_at`を保持する管理ファイル)の読み書き・更新処理、およびサードパーティサーバへの負荷を避けるリクエスト頻度制御・レジューム(中断・再開)の共通ロジックを提供する。

## Introduction

本specは、道の駅スクレイピング機能(`05-michinoeki-scraping`)・SA/PAスクレイピング機能(`06-sapa-scraping`)の双方が共通で利用する開発基盤部分を整備する。`python_util.logging`を用いた動作ログ出力の共通セットアップ、スクレイピング結果ファイルの一覧を管理する`geo-json/index.json`の読み書き・更新処理、およびサードパーティサーバへの負荷を避けるためのリクエスト頻度制御・レジューム(中断・再開)の共通ロジックを対象とする。

## Boundary Context (Optional)

- **In scope**: `python_util.logging`ベースの共通ロガー取得手段の提供、`geo-json/index.json`の読み込み・更新・保存ロジック、リクエスト間隔を制御するレート制限ロジック、スクレイピング進捗を永続化・復元するレジュームロジック
- **Out of scope**: 個別サイトのスクレイピングロジック(`05-michinoeki-scraping`、`06-sapa-scraping`)、HTTP取得・HTMLパースの共通エンジンそのものの実装(`04-scraping-engine`)、GeoJSON本体のデータスキーマ定義(`03-geojson-schema`。本specは`index.json`のファイル一覧管理のみを扱う)、`pyproject.toml`等のプロジェクト基盤自体(`01-project-scaffolding`で整備済み)
- **Adjacent expectations**: `04-scraping-engine`は本specが提供するリクエスト頻度制御・レジュームロジックを利用してHTTP取得処理を実装する。`05-michinoeki-scraping`・`06-sapa-scraping`は本specが提供するログ出力セットアップと`index.json`更新ロジックを利用してスクレイピング結果を記録する

## Requirements

### Requirement 1: 共通ロギングセットアップ

**Objective:** 開発者として、`python_util.logging`を用いた統一的なロガー取得方法を用意したい、そうすることで各スクレイピング機能が個別にロギング設定を実装せず、一貫した動作ログを出力できるようにするため

#### Acceptance Criteria

1. The Common Infrastructure shall モジュール名を指定して`python_util.logging`の`get_logger()`からロガーインスタンスを取得する共通の呼び出し手段を提供する
2. Where `pyproject.toml`の`[tool.python_util.logging]`が設定されている場合, the Common Infrastructure shall その設定(出力先ファイル・ログレベル等)に従ってログを出力する
3. Where `pyproject.toml`の`[tool.python_util.logging]`が設定されていない場合, the Common Infrastructure shall コンソール出力・ログレベル`INFO`でログを出力する
4. When スクレイピング処理が開始・終了・失敗する, the Common Infrastructure shall 該当イベントをログに記録できる呼び出しインタフェースを提供する

### Requirement 2: geo-json/index.jsonの読み書き・更新

**Objective:** 開発者として、`geo-json/index.json`の読み込み・更新・保存を共通ロジックとして扱いたい、そうすることで道の駅・SA/PAスクレイピングの双方が個別にJSON操作を実装せず、一貫した方法でファイル一覧を管理できるようにするため

#### Acceptance Criteria

1. When `geo-json/index.json`が存在する状態で読み込みが要求される, the Common Infrastructure shall 登録済みファイル一覧(`path`と`updated_at`)を読み込んで返す
2. If `geo-json/index.json`が存在しない状態で読み込みが要求された場合, then the Common Infrastructure shall 空のファイル一覧を持つ初期状態を返す
3. If `geo-json/index.json`の内容がJSONとして不正な場合, then the Common Infrastructure shall エラーを送出し読み込み処理を中断する
4. When 特定のGeoJSONファイルの`path`に対する更新が要求される, the Common Infrastructure shall 該当エントリの`updated_at`を現在時刻で更新する(未登録の`path`の場合は新規エントリとして追加する)
5. When index.jsonの更新処理が完了する, the Common Infrastructure shall 更新後の内容を`geo-json/index.json`に書き込んで永続化する
6. The Common Infrastructure shall `updated_at`をISO 8601形式のタイムスタンプで記録する

### Requirement 3: リクエスト頻度制御

**Objective:** 開発者として、スクレイピング処理全体で共通のリクエスト頻度制御を利用したい、そうすることでサードパーティサーバへの負荷を各機能が個別実装せず一貫して抑えられるようにするため

#### Acceptance Criteria

1. The Common Infrastructure shall 連続するHTTPリクエストの間に、設定可能な最小待機時間を設ける機構を提供する
2. While 直前のリクエストからの経過時間が設定された最小待機時間未満である, the Common Infrastructure shall 次のリクエストの実行前に待機する
3. The Common Infrastructure shall 呼び出し側が最小待機時間を設定変更できるようにする

### Requirement 4: レジューム(中断・再開)機能

**Objective:** 開発者として、長時間・大量ページのスクレイピング処理を中断・再開できるようにしたい、そうすることで途中でエラーや停止が発生しても最初からやり直さずに済むようにするため

#### Acceptance Criteria

1. When スクレイピング処理の進捗が更新される, the Common Infrastructure shall 処理済み範囲を示す状態を永続化する
2. When スクレイピング処理が再実行される, the Common Infrastructure shall 永続化された進捗状態を読み込み、未処理の範囲から処理を再開できるようにする
3. If 永続化された進捗状態が存在しない場合, then the Common Infrastructure shall 処理を最初から開始する
4. When スクレイピング処理が正常に完了する, the Common Infrastructure shall 永続化していた進捗状態をクリアする
