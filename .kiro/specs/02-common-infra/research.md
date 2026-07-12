# Research & Design Decisions Template

## Summary
- **Feature**: `02-common-infra`
- **Discovery Scope**: Extension(`01-project-scaffolding`が整備した基盤の上に、`python_util`依存を活用しつつ新規モジュール群を追加する)
- **Key Findings**:
  - `python_util.logging.get_logger()`は設定読み込み・コンソール/ファイル出力振り分け・フォールバックを既に内包しており、Requirement 1のAC2/AC3は`python_util`側の既存実装で満たされる。本specは呼び出し規約(共通importパス・イベントログのヘルパー)を提供すれば良い
  - `python_util.time_utility.now()`はJSTを既定としたaware `datetime`を返す。`geo-json/index.json`の`updated_at`生成にこれを再利用することで、タイムゾーン不整合のリスクを避けられる
  - `python_util`にはレート制限・レジューム機能に相当するユーティリティは存在しない。Requirement 3・4のロジックは本specが新規に実装する責務であることを確認した
  - 現状の`src/roadstop_scraper/`は空パッケージのみで、共通モジュールの配置規約が存在しない。本specがその配置パターン(`common/`サブパッケージ)を新規に確立する

## Research Log

### python_util.logging の実装詳細確認
- **Context**: Requirement 1(共通ロギングセットアップ)がAC2/AC3で要求する設定反映・デフォルトフォールバック挙動を、本specが自前で実装する必要があるか確認するため
- **Sources Consulted**: `.venv/lib/python3.11/site-packages/python_util/logging/factory.py`、`python_util/README.md`(ローカルクローン `/Users/mac-mini/develop/python_util/README.md`)
- **Findings**:
  - `get_logger(name: str | None = None) -> logging.Logger`は標準`logging.Logger`を返す。名前省略時は呼び出し元モジュール名を自動使用
  - 同名ロガーへの複数回呼び出しはハンドラ重複登録を防ぐレジストリ機構を持つ
  - `pyproject.toml`の`[tool.python_util.logging]`読み込み・コンソール/ファイル出力・モジュール単位オーバーライド・不正設定時のデフォルトフォールバックは`config_loader.py`/`handlers.py`側で完結しており、呼び出し側の実装は不要
- **Implications**: 本specの`LoggingSetup`コンポーネントは、`python_util.logging.get_logger`をそのまま公開する薄いラッパー(共通importパスの提供)と、AC4(開始・終了・失敗イベントの記録)を満たすための定型ログ出力ヘルパー関数の提供に責務を限定する

### python_util.time_utility の再利用可否確認
- **Context**: `geo-json/index.json`の`updated_at`をISO 8601形式・一貫したタイムゾーンで記録する方法を検討するため
- **Sources Consulted**: `.venv/lib/python3.11/site-packages/python_util/time_utility/__init__.py`、`python_util/README.md`
- **Findings**: `now(tz=None)`はJSTのaware `datetime`を返し、`structure.md`のindex.json例(`2026-07-12T09:00:00+09:00`)と同じJSTオフセット表記に合致する
- **Implications**: `IndexStore`コンポーネントは`datetime.now()`ではなく`python_util.time_utility.now()`を用いてタイムスタンプを生成し、シリアライズは`datetime.isoformat()`を用いる

### レート制限・レジュームの既存実装有無確認
- **Context**: `python_util`側に流用可能な実装がないか確認し、車輪の再発明を避けるため
- **Sources Consulted**: `python_util`パッケージ内のモジュール一覧(`binary_string_codec`, `logging`, `progress_display`, `test_evidence`, `time_utility`)
- **Findings**: レート制限・進捗永続化(レジューム)に相当する機能は存在しない。`progress_display`は表示専用であり永続化機構は持たない
- **Implications**: `RateLimiter`・`ResumeStore`は本specが新規設計するコンポーネントとして扱う

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Shared Kernel(共通ライブラリパッケージ) | `src/roadstop_scraper/common/`配下に独立したモジュール群(logging_setup, index_store, rate_limiter, resume_store)を配置し、下流specがimportして利用する | モジュール間疎結合、個別にテスト・拡張可能、`04-scraping-engine`以降が必要な機能だけを選択的に利用できる | モジュール数が増えると`common/`が肥大化するリスク | `01-project-scaffolding`の`src`レイアウトと自然に整合するため採用 |
| 基底クラス継承によるフレームワーク化 | `BaseScraper`のような基底クラスにロギング・レート制限・レジュームを組み込み、下流specが継承する | 呼び出し漏れを防ぎやすい | `04-scraping-engine`の設計を先取りすることになり、本specの境界(`04`を出力先とする横断ロジックの提供に留める)を超える。継承強制は疎結合の原則にも反する | 不採用。Boundary Commitmentsで「フレームワーク化はしない」ことを明記 |
| デコレータベースの横断的関心事注入 | `@rate_limited`等のデコレータでレート制限を関数に付与 | 呼び出し側コードが簡潔 | レジュームとの状態共有が複雑化し、待機時間の動的な設定変更(3.3)がしづらい | 不採用。明示的なクラスインスタンスの方がテスト容易性・設定変更容易性で優位 |

## Design Decisions

### Decision: レジューム状態の永続化先
- **Context**: Requirement 4はレジューム状態の永続化を要求するが、`structure.md`には保存先の定義がない(`geo-json/`はスクレイピング結果本体、`report/`はカバレッジ専用)
- **Alternatives Considered**:
  1. `geo-json/`配下に混在させる — スクレイピング結果と一時的な進捗状態の性質が異なり、`index.json`の管理対象を汚染するため不採用
  2. リポジトリルート直下に`.resume/`ディレクトリを新設 — 一時的・実行環境依存の状態であるためgit管理対象外とし、`report/`と同様の位置づけとする
- **Selected Approach**: リポジトリルート直下に`.resume/`ディレクトリを新設し、キー(呼び出し側が指定する文字列、例: `01_hokkaido_michinoeki`)ごとに`<key>.json`ファイルとして進捗状態を保存する
- **Rationale**: `report/`と同様、実行のたびに再生成される一時成果物であり、バージョン管理に含める意味がない。キー単位でファイルを分離することで、都道府県・サイト単位の並行実行や部分的なクリアが容易になる
- **Trade-offs**: 新規ディレクトリを追加するため`.gitignore`の更新が必要(本specが担当)。ディスク上に状態ファイルが残り続けるため、正常完了時のクリア処理(4.4)が重要になる
- **Follow-up**: `04-scraping-engine`実装時に、実際の進捗状態のデータ構造(処理済みページ番号・URL一覧等)を定義する。本specは汎用的な`dict[str, Any]`の永続化のみを提供する

### Decision: IndexStoreの状態モデル(不変データ構造 + 関数型更新)
- **Context**: `geo-json/index.json`の読み込み・更新・保存をどのようなAPI形状で提供するか
- **Alternatives Considered**:
  1. 可変クラス(`IndexManager`)がファイルハンドルを保持し、`add_entry()`が内部状態を直接書き換える
  2. 不変データ構造(`IndexData`)を返す純粋関数(`load_index`, `upsert_entry`, `save_index`)の組み合わせ
- **Selected Approach**: 不変データ構造 + 純粋関数の組み合わせを採用する
- **Rationale**: バッチ型のシーケンシャル処理(`tech.md`)であり複雑な状態管理は不要。純粋関数はテストが容易で、`Requirements Traceability`が明確になる
- **Trade-offs**: 呼び出し側が明示的に戻り値を再代入する必要がある(暗黙の副作用がない代わりに一手間増える)
- **Follow-up**: なし

## Risks & Mitigations
- 複数プロセスが同時に同じ`geo-json/index.json`や同一キーの`.resume/<key>.json`を書き込むと後勝ちで状態が失われる — 現状のバッチ型シーケンシャル処理(`tech.md`)を前提とし、並行実行のサポートは本specのスコープ外として明記する
- `python_util`の設定探索(`pyproject.toml`をカレントディレクトリから親方向へ探索)により、テスト実行時のカレントディレクトリ次第で意図しない設定が読み込まれる可能性がある — テストは常にリポジトリルートを起点に実行する運用を前提とし、必要に応じて`monkeypatch.chdir`等で明示的に制御する
- `updated_at`の生成に`datetime.now()`を誤って使用するとJSTではなくローカルタイムゾーン依存の値になる — `IndexStore`の実装規約として`python_util.time_utility.now()`の使用を必須とする(Design Decisionsに明記)

## References
- [python_util README (local clone)](file:///Users/mac-mini/develop/python_util/README.md) — `get_logger`/`time_utility`の挙動根拠
- `.kiro/steering/tech.md` — ロギング共通化・リクエスト頻度制御・レジューム方針
- `.kiro/steering/structure.md` — `geo-json/index.json`のフォーマット定義
