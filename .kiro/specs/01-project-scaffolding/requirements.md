# Requirements Document

## Project Description (Input)
他の全specの前提となる開発基盤を整備する機能。pdmによるプロジェクト初期化(`pyproject.toml`作成)、ruffによるlint/format設定、pytestによるテスト実行環境とHTML形式のカバレッジレポート出力設定(`report/`フォルダ、git対象外)、`src`レイアウトに基づくディレクトリ構成、および`python_util`(ログ出力ユーティリティ)のgit依存追加を行う。

## Introduction

本specは、道の駅・SA/PAスクレイピングアプリケーションの開発基盤を整備する。パッケージ管理(pdm)、lint/format(ruff)、テスト実行とカバレッジレポート出力(pytest)、`src`レイアウトのディレクトリ構成、および共通ロギングユーティリティ(`python_util`)の依存追加を対象とし、以降の全spec(`02-common-infra`以降)はこの基盤の上に実装される。

## Boundary Context (Optional)

- **In scope**: `pyproject.toml`初期化、依存関係管理、ruff設定、pytest/カバレッジ設定、`src`レイアウトのディレクトリ雛形、`python_util`のgit依存追加、`.gitignore`整備
- **Out of scope**: 実際のスクレイピングロジック(`04-scraping-engine`、`05-michinoeki-scraping`、`06-sapa-scraping`)、GeoJSON出力スキーマの定義(`03-geojson-schema`)、ロギング設定の具体的な実装(`02-common-infra`)、CI/CDパイプラインの構築
- **Adjacent expectations**: `02-common-infra`は本specが用意する`python_util`依存とディレクトリ構成を前提にログ出力・`index.json`管理を実装する。`05-michinoeki-scraping`・`06-sapa-scraping`は本specが定めるディレクトリ構成・テスト命名規則に従う

## Requirements

### Requirement 1: パッケージ管理と依存関係の初期化

**Objective:** 開発者として、pdmで管理されたPythonプロジェクトの雛形を用意したい、そうすることで以降の全specの実装をこの基盤の上に積み上げられるようにするため

#### Acceptance Criteria

1. The Project Scaffolding shall `pyproject.toml` にプロジェクトメタデータ(プロジェクト名、`requires-python`)を定義する
2. The Project Scaffolding shall `pyproject.toml` の依存関係に `python_util`(`git+https://github.com/t-totsuka/python_util.git`)をgit依存として含める
3. When 開発者が `pdm install` を実行する, the Project Scaffolding shall `pyproject.toml` に定義された全ての依存関係をインストールする
4. If `pdm.lock` が存在しない状態で `pdm install` が実行された場合, then the Project Scaffolding shall 依存関係を解決して `pdm.lock` を生成する
5. The Project Scaffolding shall `pdm.lock` をバージョン管理対象に含める

### Requirement 2: Lint/Format設定

**Objective:** 開発者として、コード規約から外れた変更を早期に検知したい、そうすることでレビューコストを下げ一貫したコード品質を保てるようにするため

#### Acceptance Criteria

1. The Project Scaffolding shall `pyproject.toml` の `[tool.ruff]` にlintルール(対象Pythonバージョン、行長等)を定義する
2. When 開発者が `pdm run ruff check .` を実行する, the Project Scaffolding shall プロジェクト内のPythonコードに対してlintを実行する
3. The Project Scaffolding shall importの並び順規約(isort相当のルール)をruff設定に含める

### Requirement 3: テスト実行とカバレッジレポート出力

**Objective:** 開発者として、テスト実行時に自動でHTML形式のカバレッジレポートを得たい、そうすることでテスト結果を都度手動で解析する手間を省けるようにするため

#### Acceptance Criteria

1. When 開発者が `pdm run pytest` を実行する, the Project Scaffolding shall テストスイートを実行する
2. When テストスイートの実行が完了する, the Project Scaffolding shall HTML形式のカバレッジレポートを `report/` フォルダ配下に出力する
3. The Project Scaffolding shall `report/` フォルダを `.gitignore` に登録し、バージョン管理対象から除外する
4. The Project Scaffolding shall テスト関数の日本語命名規則(`test_(テスト目的)_(テスト対象)が_(状態)だった場合_(想定される結果)`)がpytestのテスト収集規約に違反しないディレクトリ構成を提供する

### Requirement 4: ディレクトリ構成

**Objective:** 開発者として、Pythonの標準的なプロジェクト構成に沿ったディレクトリ雛形を用意したい、そうすることで以降の各specの実装が迷わず配置場所を判断できるようにするため

#### Acceptance Criteria

1. The Project Scaffolding shall `src` レイアウトに基づくソースディレクトリ構成を提供する
2. The Project Scaffolding shall テストコード配置用の `tests/` ディレクトリを `src` から分離して提供する
3. The Project Scaffolding shall スクレイピング結果の出力先として `geo-json/` フォルダを用意する

### Requirement 5: バージョン管理設定

**Objective:** 開発者として、生成物や一時ファイルが誤ってコミットされないようにしたい、そうすることでリポジトリの肥大化や不要な差分を防げるようにするため

#### Acceptance Criteria

1. The Project Scaffolding shall `report/` フォルダ、Python仮想環境ディレクトリ、ツールキャッシュディレクトリ(`__pycache__`等)を `.gitignore` に登録する
2. The Project Scaffolding shall プロジェクトルートに `README.md` の初期雛形を用意する
