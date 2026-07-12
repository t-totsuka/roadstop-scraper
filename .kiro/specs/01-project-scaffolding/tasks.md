# Implementation Plan

- [x] 1. Foundation: pyproject.tomlによるプロジェクト基盤の宣言
- [x] 1.1 pdmプロジェクトメタデータとビルド設定を定義する
  - プロジェクト名と`requires-python`(Python 3.11以上)を`pyproject.toml`に宣言する
  - `[build-system]`(`pdm-backend`)と`[tool.pdm] distribution = true`を設定し、`src`レイアウトパッケージが編集可能インストールされる下地を用意する
  - 観測可能な完了条件: `pdm install`が構文エラーなく起動する
  - _Requirements: 1.1_

- [x] 1.2 python_utilのgit依存を追加しロックファイルを生成する
  - `dependencies`に`python_util`(`git+https://github.com/t-totsuka/python_util.git`)をgit direct referenceとして追加する
  - `pdm install`を実行して依存関係を解決し、`pdm.lock`を生成する
  - 観測可能な完了条件: `pdm.lock`に`python_util`の解決済みコミットが記録され、`pdm.lock`がバージョン管理対象になる
  - _Requirements: 1.2, 1.3, 1.4, 1.5_

- [x] 1.3 ruffによるlint/format設定を追加する
  - `[tool.ruff]`に対象Pythonバージョン・行長を設定する
  - `[tool.ruff.lint]`にルールセット(`E`, `F`, `I`, `UP`, `B`)を設定し、import順序規約を含める
  - 観測可能な完了条件: `pdm run ruff check .`が設定エラーなく実行される
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 1.4 pytestとカバレッジレポート出力設定を追加する
  - `[tool.pytest.ini_options]`にHTML形式のカバレッジレポートを`report/`フォルダへ出力する設定を追加する
  - 観測可能な完了条件: `pyproject.toml`の設定により、後続タスクで`pdm run pytest`を実行した際に`report/`へのHTML出力が行われる状態になる
  - _Requirements: 3.1, 3.2_

- [x] 2. Core: ディレクトリ雛形とプロジェクトファイルの整備
- [x] 2.1 (P) srcレイアウトのソースパッケージ雛形を作成する
  - `src/roadstop_scraper/`パッケージ(空の`__init__.py`)を作成する
  - 観測可能な完了条件: `src/roadstop_scraper/__init__.py`が存在し、パッケージとして認識される
  - _Requirements: 4.1_
  - _Boundary: SrcPackage_

- [x] 2.2 (P) テストパッケージ雛形を作成する
  - `src`から分離した`tests/`ディレクトリ(`__init__.py`)を作成する
  - 観測可能な完了条件: `tests/__init__.py`が存在し、pytestの収集対象ディレクトリとして機能する
  - _Requirements: 3.4, 4.2_
  - _Boundary: TestsPackage_

- [x] 2.3 (P) geo-json出力ディレクトリの雛形を作成する
  - スクレイピング結果の出力先として`geo-json/`ディレクトリを作成し、空ディレクトリをgit管理下に置くためのプレースホルダを配置する
  - 観測可能な完了条件: `geo-json/`ディレクトリがリポジトリに存在し、`git status`で追跡される
  - _Requirements: 4.3_
  - _Boundary: GeoJsonDir_

- [x] 2.4 (P) .gitignoreを整備する
  - `report/`フォルダ、Python仮想環境ディレクトリ、`__pycache__`等のツールキャッシュディレクトリを`.gitignore`に登録する
  - 観測可能な完了条件: `.gitignore`に登録したパターンが存在する
  - _Requirements: 3.3, 5.1_
  - _Boundary: GitIgnore_

- [x] 2.5 (P) README.mdの初期雛形を作成する
  - プロジェクトルートに`README.md`の初期雛形を作成する
  - 観測可能な完了条件: `README.md`がリポジトリルートに存在する
  - _Requirements: 5.2_
  - _Boundary: ReadmeSkeleton_

- [x] 3. pdmによる依存関係とsrcパッケージ解決の統合検証
  - `pdm install`を実行し、`python_util`のインストールと`src/roadstop_scraper`の編集可能インストールが同時に成立することを確認する
  - 観測可能な完了条件: 仮想環境内で`import roadstop_scraper`および`import python_util.logging`が成功する
  - _Requirements: 1.1, 1.4, 1.5, 4.1_
  - _Depends: 1.1, 1.2, 2.1_

- [x] 4. Validation: 基盤設定の動作検証
- [x] 4.1 日本語命名テストによるpytest収集とカバレッジ出力の検証
  - `tests/`配下に日本語命名規則(`test_(テスト目的)_(テスト対象)が_(状態)だった場合_(想定される結果)`)に沿ったダミーテストを1件作成する
  - `pdm run pytest`を実行する
  - 観測可能な完了条件: ダミーテストが収集・成功し、`report/index.html`にHTML形式のカバレッジレポートが生成される
  - _Requirements: 3.1, 3.2, 3.4_
  - _Depends: 1.4, 2.2_

- [x] 4.2 ruff lintの動作検証
  - `pdm run ruff check .`を実行する
  - 観測可能な完了条件: `src/`・`tests/`配下のコードに対してruffが0件の指摘で終了する
  - _Requirements: 2.2_
  - _Depends: 1.3, 2.1_

- [x] 4.3 .gitignore除外動作の検証
  - `pdm run pytest`実行後に`git status`を実行する
  - 観測可能な完了条件: `report/`・仮想環境・ツールキャッシュディレクトリが未追跡ファイルとして表示されない
  - _Requirements: 3.3, 5.1_
  - _Depends: 2.4, 4.1_
