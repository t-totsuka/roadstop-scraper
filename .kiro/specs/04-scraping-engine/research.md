# Research & Design Decisions

## Summary

- **Feature**: `04-scraping-engine`
- **Discovery Scope**: Extension(`02-common-infra`・`03-geojson-schema`が確立した基盤・パターンの上に新規パッケージを追加する。light discoveryを実施)
- **Key Findings**:
  - requests(2.34.2、2026-05リリース)・beautifulsoup4(4.15.0、2026-06リリース)はいずれもPython 3.11対応・活発に保守されており、採用に支障なし。requestsは`charset_normalizer`を同梱しエンコーディング推定(AC 1.4)に利用できる
  - 対象4サイトのHTTPヘッダを実測した結果、HTML3サイトはすべて`Content-Type`で`charset=utf-8`を宣言、JSONエンドポイント(w-holdings)はcharset無指定(JSON既定のUTF-8)。エンコーディング解決はヘッダ優先+推定フォールバックの単純な方式で足りる
  - `02-common-infra`の`RateLimiter`は「`wait()`完了時刻から最小間隔」を保証するブロッキング実装のため、リトライ待機を別途sleepしてから`wait()`を通す構成で、リトライ待機(2.5)とレート制限(1.3)を両立できる
  - `python_util.logging`の`config_loader.py`(tomllib+cwd上方探索+不正時warning・デフォルトフォールバック)が、`pyproject.toml`設定読み込み(2.7/2.8)の踏襲可能な参照実装であることを確認した

## Research Log

### ライブラリ選定とバージョン確認

- **Context**: ギャップ分析でrequests+BeautifulSoupが第一候補となり、ユーザー決定で採用が確定。最新バージョンとPython 3.11互換性の確認が必要
- **Sources Consulted**: [requests · PyPI](https://pypi.org/project/requests/)、[beautifulsoup4 · PyPI](https://pypi.org/project/beautifulsoup4/)、[Requests公式ドキュメント](https://requests.readthedocs.io/)
- **Findings**:
  - requests最新は2.34.2(2026-05-14リリース)。Python 3.11対応。`charset_normalizer`を依存として同梱し、`Response.apparent_encoding`でエンコーディング推定が可能
  - beautifulsoup4最新は4.15.0(2026-06-07リリース)。Python >=3.7対応、MITライセンス
  - いずれもpure Python wheelで、pdmでの導入に特別な考慮は不要
- **Implications**: `pdm add requests beautifulsoup4`で導入する。バージョン制約は`requests>=2.34`・`beautifulsoup4>=4.15`を下限とする

### 対象サイトの文字エンコーディング実測

- **Context**: AC 1.4(エンコーディング解決)の実装方式を決めるため、対象4サイトの実際のレスポンスヘッダを確認した(ギャップ分析のResearch Needed 6)
- **Sources Consulted**: `curl -sI`による各サイトへのHEADリクエスト(2026-07-12実施)
- **Findings**:
  - michi-no-eki.jp(道の駅詳細): `text/html; charset=utf-8`
  - driveplaza.com(NEXCO東日本詳細): `text/html; charset=UTF-8`
  - sapa.c-nexco.co.jp(NEXCO中日本詳細): `text/html; charset=utf-8`
  - w-holdings.co.jp `map-search.json`: `application/json`(charset無指定。JSONの既定はUTF-8)
- **Implications**: 全対象サイトがUTF-8。エンコーディング解決は「`Content-Type`ヘッダのcharset優先、無指定時は`apparent_encoding`(charset_normalizer)へフォールバック」で十分。Shift_JIS等の特殊対応は不要

### BeautifulSoupパーサバックエンドの選定

- **Context**: `html.parser`(標準ライブラリ)と`lxml`(高速・寛容だがC拡張の依存追加)のどちらを使うか(ギャップ分析のResearch Needed 1)
- **Sources Consulted**: BeautifulSoup公式ドキュメントのパーサ比較、対象サイトのHTML実態(03のresearch.md)
- **Findings**:
  - 本プロジェクトの処理速度はレート制限の待機時間(リクエスト間隔)が支配的で、パース速度の差は全体所要時間にほぼ影響しない
  - 対象サイトのHTMLは通常のCMS出力であり、`html.parser`で処理できない壊れ方をしている兆候はない
  - プロジェクトは依存追加に抑制的な方針(pydantic不採用の実績)
- **Implications**: `html.parser`を採用し、依存追加はrequests・beautifulsoup4の2つに留める。将来パース不能なHTMLに遭遇した場合のみlxml導入を再検討

### リトライ待機とRateLimiterの相互作用

- **Context**: AC 2.5(リトライ前の待機)とAC 1.3(レート制限の遵守)の関係整理(ギャップ分析のResearch Needed 2)
- **Sources Consulted**: `src/roadstop_scraper/common/rate_limiter.py`の実装
- **Findings**:
  - `RateLimiter.wait()`は「直前の`wait()`完了時刻から最小間隔」を保証する。`wait()`の後に任意のsleepを挟んでも次回`wait()`の基準時刻は前回`wait()`完了時点のまま
  - リトライ待機を先にsleepしてから`wait()`を呼ぶ順序にすると、両方の待機条件が確実に満たされる(実待機は概ね`max`ではなく逐次加算になるが、対象サーバ保護の観点では安全側)
- **Implications**: 送信試行のたびに「(2回目以降は)リトライ待機をsleep → `RateLimiter.wait()` → 送信」の順で実行する設計とする。リトライ待機時間は固定値(設定可能)とし、指数バックオフは導入しない(最大リトライ回数が小さく、レート制限が既に間隔を保証しているため過剰)

### pyproject.toml設定読み込みの方式

- **Context**: AC 2.7/2.8(リトライ回数・待機時間・タイムアウトの外部設定)の実装方式(ギャップ分析のResearch Needed 3)
- **Sources Consulted**: `.venv/.../python_util/logging/config_loader.py`(参照実装)
- **Findings**:
  - `python_util`方式: `tomllib.loads`でパース → `Path.cwd()`から上方探索で`pyproject.toml`を発見 → テーブル不在なら既定値 → 解析失敗・不正値はwarningを出して既定値へフォールバック
  - この実装は`[tool.python_util.logging]`専用の非公開モジュールで、汎用APIとしては公開されていないため再利用不可(パターンの踏襲のみ)
- **Implications**: テーブル名は`[tool.roadstop_scraper.scraping]`とし、`timeout_seconds`・`max_retries`・`retry_wait_seconds`・`min_request_interval_seconds`の4キーを定義する。読み込みは`tomllib`+上方探索+不正時warning・既定値フォールバックの同型実装を`scraping/config.py`に持つ

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 新規`scraping/`パッケージ+コンポジション(採用) | `fetcher`・`parser`・`extract`・`config`・`resume`・`errors`の独立モジュール群を`src/roadstop_scraper/scraping/`に配置し、`common/`の部品を内部利用 | spec境界とパッケージ境界が一致、`geojson/`(03)と同じ構成パターン、05/06は必要な部品だけ選択利用できる | モジュール間のインタフェース設計が必要 | ギャップ分析Option B。ユーザー決定済み |
| `common/`への追加 | `common/`にfetcher等を同居させる | 新規パッケージ不要 | 02のBoundary Context(エンジンはOut of scope)と矛盾、`common/`肥大化 | 不採用(ギャップ分析Option A) |
| `BaseScraper`継承フレームワーク | 基底クラスにfetch/parse/resumeを組み込み05/06が継承 | 呼び出し漏れ防止 | 02のresearch.mdで明示的に不採用済み(継承強制は疎結合に反する) | 不採用 |

## Design Decisions

### Decision: HTTP取得はrequests(同期)+セッション注入で実装する

- **Context**: HTTP取得(Requirement 1・2)の実装基盤と、テスト時のHTTPスタブ化の方式を決める必要がある
- **Alternatives Considered**:
  1. requests(同期) — 既存基盤(逐次前提)と整合
  2. httpx — async対応だが現前提では不要
  3. Scrapy — 02の`RateLimiter`・`ResumeStore`と機能重複、Twistedの非同期モデルが逐次前提と競合
- **Selected Approach**: 案1(ユーザー決定)。`PageFetcher`はコンストラクタで`requests.Session`(互換オブジェクト)を注入可能とし、既定では内部生成する
- **Rationale**: `RateLimiter`(ブロッキング)・`ResumeStore`(単一プロセス)と完全に整合し、学習・保守コストが最小。セッション注入により、requests-mock等の追加依存なしでテスト時のスタブ化が可能
- **Trade-offs**: 並行取得はできないが、本プロジェクトの非目標(レート制限で意図的に逐次化している)
- **Follow-up**: tech.mdの「BeautifulSoup/Scrapy使い分け検討中」の記述を本決定で更新する(steering反映)

### Decision: パース抽象化は`HtmlPage`ラッパーでBeautifulSoupを隠蔽する

- **Context**: AC 3.3(パースライブラリの実装詳細を呼び出し側へ露出させない)の実現方式
- **Alternatives Considered**:
  1. BeautifulSoupオブジェクトをそのまま返す — 抽象化にならず、05/06がbs4 APIへ直接依存する
  2. CSSセレクタベースの薄いラッパー`HtmlPage`を定義し、テキスト・属性値の取得メソッドのみ公開する
- **Selected Approach**: 案2。`HtmlPage`は「任意取得(見つからなければ`None`)」と「必須取得(見つからなければ`StructureChangedError`)」の2系統のメソッドを持ち、CSSセレクタ文字列で要素を指定する
- **Rationale**: 05/06の抽出コードはCSSセレクタと項目名だけを扱えばよくなり、bs4のバージョンアップ・差し替えの影響がエンジン内に閉じる。必須/任意の区別をAPIレベルで持つことで、構造変化検知(4.1)が抽出コードの規律に依存せず構造的に働く
- **Trade-offs**: bs4の高度な機能(兄弟走査等)は公開されないが、必要になった時点でラッパーへメソッド追加する方針とする
- **Follow-up**: 05/06の実装で不足するセレクタ操作が出た場合はエンジン側へ追加する(05/06にbs4を直接importさせない)

### Decision: 抽出結果は「宣言的なFieldSpec+汎用ExtractedRecord」で受け渡す

- **Context**: AC 6.1〜6.3(構造化受け渡し・source_url対応付け・欠損判別)と4.1(抽出必須指定)を一体で満たすAPIの形(ギャップ分析のResearch Needed 4)
- **Alternatives Considered**:
  1. 汎用dictを返す — 欠損判別・必須指定の規約が呼び出し側任せになる
  2. `FacilityProperties`を直接返す — スキーマ変換(05/06の責務)をエンジンに取り込んでしまい境界違反
  3. 抽出項目を`FieldSpec`(項目名・セレクタ・必須フラグ)で宣言し、結果を`ExtractedRecord`(source_url+項目名→値のマップ、欠損は`None`)で返す
- **Selected Approach**: 案3。必須項目の欠落は`StructureChangedError`、任意項目の欠落は`None`値として返す
- **Rationale**: 「どの項目が必須か」が宣言として一箇所に集まり、構造変化検知の対象が明示される。エンジンはドメイン(道の駅/SA/PA)を知らない汎用レコードに留まり、`FacilityProperties`へのマッピングは05/06の責務という境界が保たれる
- **Trade-offs**: 属性値の後処理(正規表現での座標抽出等)は05/06側の実装になるが、それはドメイン知識であり妥当な配置
- **Follow-up**: NEXCO西日本のJSONソースは`FieldSpec`を使わず`fetch_json`の結果を直接マッピングする(パース抽象化の対象外であることをdesign.mdに明記)

### Decision: レジューム連携は「処理済みURL集合」を`ResumeStore`に保存するトラッカーとして提供する

- **Context**: AC 5.3/5.4のレジューム連携で、`ResumeStore`(汎用dict永続化)の上にどんな状態形状・APIを定義するか(ギャップ分析のResearch Needed 5)
- **Alternatives Considered**:
  1. 状態形状を05/06に委ねる — 双方が同型のURL管理を重複実装する
  2. `UrlResumeTracker`(処理済みURL集合の照会・追加・クリア)をエンジンが提供する
- **Selected Approach**: 案2。状態は`{"processed_urls": [...]}`の形で`ResumeStore`に保存し、`mark_processed(url)`のたびに永続化する
- **Rationale**: 05/06のクロールは「URL一覧を順に処理する」構造が共通(検索一覧→詳細ページ)。URL単位のスキップ判定はその共通部分であり、エンジン側で一度だけ実装するのが妥当
- **Trade-offs**: URL以外の進捗単位(ページ番号等)が必要になった場合は`ResumeStore`を直接使う余地を残す(トラッカーは強制しない)
- **Follow-up**: `mark_processed`の都度保存はURL件数(数百〜千数百件)では性能上問題ないことをテストで確認する

### Decision: リトライは固定待機+全試行でレート制限を通す

- **Context**: AC 2.2〜2.5の実現方式(Research Logの「リトライ待機とRateLimiterの相互作用」参照)
- **Alternatives Considered**:
  1. urllib3の`Retry`アダプタ — ステータス別制御は可能だがレート制限・ログ(5.2)との統合点がrequests内部に隠れる
  2. エンジン自前のリトライループ(固定待機)
- **Selected Approach**: 案2。「リトライ待機sleep(2回目以降)→`RateLimiter.wait()`→送信」を1試行とするループを`PageFetcher`が持つ。5xx・タイムアウト・接続エラーはリトライ、4xxは即時確定
- **Rationale**: 試行ごとのログ出力(5.2)・レート制限適用(1.3)・待機(2.5)の順序をエンジンのコードで明示的に制御でき、テストも書きやすい。指数バックオフはレート制限が既に間隔を保証しているため導入しない
- **Trade-offs**: urllib3の実績あるリトライ実装を使わないが、ループ自体は単純で自前実装のリスクは小さい

## Risks & Mitigations

- 対象サイトのHTML構造変更で抽出が壊れる — `StructureChangedError`(URL・セレクタ付き)+警告ログで即時検知可能にする(Requirement 4そのものが緩和策)
- requestsのデフォルトUser-Agentがブロックされる可能性 — `PageFetcher`が識別可能なUser-Agentを設定できるようにする(既定値は設計で定義)
- `mark_processed`の都度保存によるI/O — 件数規模(高々千数百URL)では無視できる想定。問題化したら保存間引きを検討
- 設定テーブルの不正値による意図しない高頻度アクセス — 不正値は既定値フォールバック+warningとし、「設定ミスでレート制限が無効化される」方向の失敗を防ぐ

## References

- [requests · PyPI](https://pypi.org/project/requests/) — 採用HTTPクライアント(2.34.2)
- [Requests公式ドキュメント](https://requests.readthedocs.io/) — タイムアウト・エンコーディング・Session仕様
- [beautifulsoup4 · PyPI](https://pypi.org/project/beautifulsoup4/) — 採用HTMLパーサ(4.15.0)
- [Beautiful Soup Documentation](https://beautiful-soup-4.readthedocs.io/en/latest/) — パーサバックエンド比較
- `.kiro/specs/04-scraping-engine/gap-analysis.md` — 実装ギャップ分析(Option B採用の経緯)
- `.kiro/specs/03-geojson-schema/research.md` — 対象サイトの実HTML/JSON構造調査
