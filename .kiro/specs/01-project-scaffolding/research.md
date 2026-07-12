# Research & Design Decisions

## Summary
- **Feature**: `01-project-scaffolding`
- **Discovery Scope**: Simple Addition(開発基盤・設定ファイルの整備。ランタイムロジックは含まない)
- **Key Findings**:
  - 同一開発者が運用する姉妹リポジトリ`python_util`(`/Users/mac-mini/develop/python_util`)が、pdm + ruff + pytest-cov による実運用済みの`pyproject.toml`構成を持ち、本specの雛形として直接参考にできる
  - `python_util`はカバレッジ出力先を`reports/coverage_html`(複数形)としているが、本プロジェクトのsteering(`structure.md`)は`report/`(単数形)を明示しているため、本specでは`report/`を採用し`python_util`の命名は踏襲しない
  - pdmでgit上の依存を追加する場合は`"python_util @ git+https://github.com/t-totsuka/python_util.git"`というPEP 508 direct reference構文を`dependencies`に記述する
  - `python_util`にはpre-commitフックによるtest-evidence.md自動生成の仕組みがあるが、requirements.mdで要求されておらず、本specのNon-Goalsとして明示的にスコープ外とする

## Research Log

### pdmによるgit依存関係の追加方法
- **Context**: `python_util`をgit依存として追加する具体的な構文を確認する必要があった
- **Sources Consulted**: 姉妹リポジトリ`python_util`の`pyproject.toml`(`build-system`/`[tool.pdm] distribution = true`の設定)、PEP 508 direct reference構文
- **Findings**: `pdm add "python_util @ git+https://github.com/t-totsuka/python_util.git"`を実行すると、`pyproject.toml`の`dependencies`に直接参照URLが追記され、`pdm.lock`に解決済みのコミット情報が記録される
- **Implications**: `pyproject.toml`に手書きする場合も同じ文字列形式を用いる。特定バージョンへの固定が必要になった場合は`@ git+https://...@<tag>`の形式に拡張できる(本specでは既定でデフォルトブランチ追従とし、タグ固定は要求されていない)

### カバレッジレポート出力先の命名差異
- **Context**: 姉妹リポジトリ`python_util`は`reports/`(複数形)、本プロジェクトのsteering(`structure.md`)は`report/`(単数形)を指定しており、命名が食い違っていた
- **Sources Consulted**: `.kiro/steering/structure.md`、`python_util/pyproject.toml`の`[tool.pytest.ini_options]`
- **Findings**: steeringは本プロジェクト固有の合意事項であり、`python_util`の命名は別プロジェクトの慣習に過ぎない
- **Implications**: 本specでは`report/`(単数形)を正とし、`pytest`のカバレッジ出力設定・`.gitignore`に反映する

### ruff設定の踏襲範囲
- **Context**: どのruffルールセットを採用するか判断が必要だった
- **Sources Consulted**: `python_util/pyproject.toml`の`[tool.ruff.lint]`(`E`, `F`, `I`, `UP`, `B`)
- **Findings**: 同一開発者が別プロジェクトで運用実績のあるルールセットであり、大きく逸脱する理由がない
- **Implications**: 本specでも同じルールセット(`E`, `F`, `I`, `UP`, `B`)を初期値として採用する

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| pyproject.toml(PEP 621)+ pdm | 宣言的な単一設定ファイルで依存関係・lint・テストを管理 | ツール標準に準拠、`python_util`で実績あり | pdm特有のロックファイル運用に習熟が必要 | `tech.md`で既定済み |
| setup.py + requirements.txt(legacy) | 従来型のスクリプトベース設定 | 情報が多く枯れている | 宣言的でなく、ruff/pytest設定が分散する | steeringのpdm方針と矛盾するため不採用 |

## Design Decisions

### Decision: `report/`ディレクトリの命名をsteering優先で確定
- **Context**: 姉妹リポジトリ`python_util`は`reports/`だが、本プロジェクトのsteering(`structure.md`)は`report/`
- **Alternatives Considered**:
  1. `python_util`に合わせ`reports/`にする
  2. steering通り`report/`にする
- **Selected Approach**: `report/`(steeringに準拠)
- **Rationale**: steeringは本プロジェクト固有の合意であり優先度が高い。`python_util`は別プロジェクトの慣習であり本プロジェクトを拘束しない
- **Trade-offs**: `python_util`との表記統一は失われるが、本プロジェクト内の一貫性(既に`structure.md`で参照済み)を優先する
- **Follow-up**: 実装タスクで`pyproject.toml`のカバレッジ出力パスを誤って`reports`と書かないよう明示する

### Decision: `python_util`の依存参照方式
- **Context**: gitリポジトリ上のパッケージをpdmでどう参照するか
- **Alternatives Considered**:
  1. PyPIに公開して通常の名前付き依存にする
  2. gitのdirect referenceで依存追加する
- **Selected Approach**: git direct reference(`python_util @ git+https://github.com/t-totsuka/python_util.git`)
- **Rationale**: `python_util`は現時点でPyPI未公開の個人リポジトリであり、`tech.md`のsteeringも同構文を明記済み
- **Trade-offs**: PyPIのバージョニング・キャッシュ機構は使えず、`pdm install`のたびにgit参照の解決が必要になる
- **Follow-up**: ネットワーク不通時のinstall失敗は運用でカバーする(自動リトライ等は本specのスコープ外)

## Risks & Mitigations

- `python_util`のデフォルトブランチが将来変更・削除されると依存解決が失敗する — 将来的にタグ/コミットハッシュ固定を検討する(本specでは対象外、フォローアップ事項として記録)
- `report/`と`reports/`の命名を実装時に混同する — design.md・tasksでパス文字列を明示し、レビュー時に確認する
- srcレイアウトとpdmのビルド設定(`[tool.pdm] distribution`)を誤ると`pdm install`でパッケージが正しく解決されない — `python_util`の実績あるビルド設定(`pdm-backend`)をそのまま踏襲する

## References
- 姉妹リポジトリ `python_util`(ローカルパス: `/Users/mac-mini/develop/python_util`)— pdm/ruff/pytest構成の実運用済み参考実装
- `.kiro/steering/tech.md` — pdm/ruff/python_util依存方針
- `.kiro/steering/structure.md` — `report/`・`geo-json/`・`src`レイアウト方針
