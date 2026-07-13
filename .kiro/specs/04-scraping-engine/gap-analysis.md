# Implementation Gap Analysis

## Summary

- **Feature**: `04-scraping-engine`
- **Discovery Scope**: Extension(`02-common-infra`・`03-geojson-schema`が確立した基盤・パターンの上に、新規パッケージとしてスクレイピングエンジンを追加する)
- **Key Findings**:
  - HTTP取得・HTMLパースに必要な外部ライブラリ(HTTPクライアント・BeautifulSoup等)が未導入。現在の依存は`python_util`のみで、ライブラリ選定が設計フェーズの主要な決定事項になる
  - `02-common-infra`の`RateLimiter`(ブロッキング・逐次実行前提)・`ResumeStore`(dict状態のキー単位永続化)・`logging_setup`はそのまま利用可能。ただしいずれも汎用部品のため、「URL単位の処理済み管理」「リトライ待機との関係」はエンジン側で設計する必要がある
  - `RateLimiter`・`ResumeStore`が単一プロセス・逐次実行を前提とするため、独自のスケジューラ・並行制御・レジューム機構を持つScrapyとはアーキテクチャが競合する。既存基盤を活かすなら requests系+BeautifulSoup の構成が自然
  - `pyproject.toml`からの設定読み込み(Requirement 2.7)は既存コードに汎用機構がないが、`python_util.logging`の`config_loader.py`(tomllib+上方探索+不正時デフォルトフォールバック)が踏襲可能な参照実装になる

## Current State Investigation

### 既存アセット

| アセット | 場所 | 本specとの関係 |
|---------|------|--------------|
| `RateLimiter` | `src/roadstop_scraper/common/rate_limiter.py` | Requirement 1.3で利用。`wait()`のブロッキング待機、単一スレッド・逐次呼び出し前提 |
| `ResumeStore` | `src/roadstop_scraper/common/resume_store.py` | Requirement 5.3/5.4で利用。キー単位でdict状態を`.resume/<key>.json`に永続化。破損時は警告ログ+`None`(最初から開始) |
| `logging_setup` | `src/roadstop_scraper/common/logging_setup.py` | Requirement 5.1/5.2で利用。`get_logger()`再公開+開始/終了/失敗イベントヘルパー |
| `write_text_atomic` | `src/roadstop_scraper/common/_atomic_io.py` | 直接は不要(ファイル出力は03の`writer`責務)。レジューム永続化は`ResumeStore`経由で利用済み |
| GeoJSONモデル | `src/roadstop_scraper/geojson/models.py` | Requirement 6の後段マッピング先。`FacilityFeature`/`FacilityProperties`(frozen dataclass、必須4項目+任意項目) |
| `python_util.logging.config_loader` | `.venv/.../python_util/logging/config_loader.py` | Requirement 2.7の参照実装。ただし`[tool.python_util.logging]`専用の非公開実装であり、汎用テーブル読み込みAPIは公開されていない |

### 支配的なコーディングパターン(踏襲すべき規約)

- `@dataclass(frozen=True)`による不変データ型+モジュールレベル関数、`__all__`による公開制御
- 独自例外は意味のある名前(`IndexFileCorruptedError`、`InvalidGeoJsonFilenameError`等)+日本語メッセージで文脈を付与
- パッケージ`__init__.py`での公開API集約(`geojson/__init__.py`方式。`common/__init__.py`は空で、モジュール直接importの方式。どちらに揃えるかは設計判断)
- 日本語docstring(コード本体はHow観点)、`from __future__ import annotations`、Python 3.11+
- テストは`tests/`配下、日本語ベースのテスト関数名
- 外部依存は最小(現在`python_util`のみ)。バリデーションは手書き(pydantic等は不採用の実績あり)

### 統合サーフェス

- **入力側**: `02-common-infra`のAdjacent expectations に「`04-scraping-engine`は本specが提供するリクエスト頻度制御・レジュームロジックを利用してHTTP取得処理を実装する」と明記済み。境界は整合している
- **出力側**: `03-geojson-schema`の`FacilityProperties`が最終マッピング先。スキーマへの変換自体は05/06の責務のため、エンジンは「取得元URL付き・欠損判別可能な構造化データ」を返せばよい
- **対象サイトの実態**(03のresearch.mdより): HTML詳細ページ(michi-no-eki.jp、driveplaza.com、sapa.c-nexco.co.jp)と、JSONエンドポイント(w-holdings.co.jpの`map-search.json`)が混在。Requirement 1.2のJSON取得対応はこの実態に基づく

## Requirement-to-Asset Map

| Requirement | 既存アセット | ギャップ | タグ |
|------------|------------|---------|------|
| 1. HTTPコンテンツ取得 | `RateLimiter`(1.3) | HTTPクライアントライブラリが未導入。取得処理・エンコーディング解決(1.4)・エラーステータスの扱い(1.5)はすべて新規 | **Missing**(HTTPクライアント選定は Research Needed) |
| 2. タイムアウト・リトライ | なし | リトライループ・タイムアウト適用は新規。リトライ待機(2.5)と`RateLimiter`の最小間隔の関係整理が必要 | **Missing** + **Unknown**(待機時間の重畳方針) |
| 2.7/2.8 pyproject設定 | `python_util.logging.config_loader`(参照実装、非公開) | 汎用の設定読み込みモジュールが存在しない。テーブル名(例: `[tool.roadstop_scraper.scraping]`)・探索起点・不正値フォールバックの設計が必要 | **Missing**(実装パターンは既知) |
| 3. パース抽象化 | なし | BeautifulSoup未導入。セレクタ指定の抽出API・実装詳細の隠蔽(3.3)は新規 | **Missing**(BS4/Scrapy使い分けは Research Needed) |
| 4. 構造変化検知 | 例外設計パターン(`common`/`geojson`の独自例外) | 構造変化専用例外・URL/セレクタ情報の付与・警告ログは新規。パターンは既存踏襲で実装可能 | **Missing**(パターンは確立済み) |
| 5.1/5.2 ロギング連携 | `logging_setup`(`get_logger`+イベントヘルパー) | HTTP取得イベント(開始・成功・失敗・リトライ)のログ語彙をエンジン側で追加 | 小さな **Missing** |
| 5.3/5.4 レジューム連携 | `ResumeStore`(汎用dict永続化) | 「処理済みURLのスキップ・記録」に対応する状態の形状(URL集合等)とヘルパーAPIが未定義 | **Unknown**(状態スキーマは05/06の走査方式に依存) |
| 6. 構造化受け渡し | `geojson`モデル(マッピング先として) | エンジンの抽出結果表現(汎用レコード)が未定義。欠損判別(6.3)・取得元URL対応付け(6.2)を含む | **Missing** + **Unknown**(汎用dict vs 型付きレコード) |

### 制約(Constraint)

- `RateLimiter`・`ResumeStore`は**単一プロセス・逐次実行前提**。エンジンもこの前提を引き継ぐ(並行クロールは非目標)
- `02-common-infra`のresearch.mdで「`BaseScraper`のようなフレームワーク化はしない」ことが明示的に不採用となっている。エンジンは継承強制ではなく、部品の組み合わせ(コンポジション)で提供するのが既存決定と整合する
- 依存追加に抑制的な方針(pydantic不採用の実績)。ライブラリ追加はHTTPクライアント+パーサの必要最小限に留めるのが一貫する

## Implementation Approach Options

### Option A: `common/`パッケージの拡張

`src/roadstop_scraper/common/`に`fetcher.py`・`parser.py`等を追加する。

- ✅ 新規パッケージ不要、既存の`common`部品と同居して距離が近い
- ❌ `02-common-infra`のBoundary Contextが「HTTP取得・HTMLパースの共通エンジンそのもの」を明示的にOut of scopeとしており、spec境界とパッケージ境界がずれる
- ❌ `common/`の肥大化リスク(02のresearch.mdでも懸念として記録済み)

### Option B: 新規パッケージ `scraping/` の作成(推奨方向)

`src/roadstop_scraper/scraping/`(仮)として、`fetcher`(HTTP取得+リトライ)・`parser`(パース抽象化)・`config`(pyproject設定読み込み)・例外群を新規作成し、`common/`の部品を内部で利用する。

- ✅ spec境界(02=基盤部品、04=エンジン)とパッケージ境界が一致する
- ✅ `geojson/`パッケージ(03)と同じ「spec単位のサブパッケージ」構成で一貫する
- ✅ 独立したテスト・公開API(`__init__.py`集約)を設計しやすい
- ❌ パッケージ間のインタフェース設計(例外の公開範囲・configの所在)を丁寧に決める必要がある

### Option C: ハイブリッド(新規`scraping/`+`common/`への小さな追加)

エンジン本体はOption Bどおり新規パッケージとし、**pyproject設定読み込みだけ**を汎用機構として`common/`へ置く(将来05/06が独自設定を持つ場合に再利用可能)。

- ✅ 設定読み込みの再利用性が上がる
- ❌ 現時点で04以外に利用者がいない機構を`common/`に先行配置することになり、YAGNI気味
- 判断基準: 05/06にも`pyproject.toml`設定の需要が見込まれるか(設計フェーズで判断)

## ライブラリ選定の候補(Research Needed)

| Option | Description | Strengths | Risks / Limitations |
|--------|-------------|-----------|---------------------|
| requests + BeautifulSoup | 同期HTTPクライアント+HTMLパーサ | `RateLimiter`(ブロッキング)・`ResumeStore`(逐次)とアーキテクチャが完全に整合。学習コスト最小。`charset_normalizer`同梱でエンコーディング解決(1.4)も賄える | 並行取得はできない(ただし本プロジェクトの非目標) |
| httpx + BeautifulSoup | sync/async両対応のモダンなクライアント | requestsとほぼ同じ同期APIで将来async化の余地 | async能力は現前提(逐次実行)では不要。依存としてやや新しい |
| Scrapy | クロールフレームワーク(スケジューラ・AutoThrottle・JOBDIR再開内蔵) | レート制御・レジューム・リトライを框架として内蔵 | **02が実装済みの`RateLimiter`・`ResumeStore`と機能重複**し、非同期(Twisted)モデルが既存の逐次前提と競合。tech.mdの「使い分け検討中」への最終回答を設計フェーズで出す必要がある |

パーサバックエンド(BS4採用時): 標準の`html.parser`(依存追加なし)か`lxml`(高速・寛容)かも設計フェーズで決定する。

## Implementation Complexity & Risk

- **Effort: M(3〜7日)** — 新規パッケージ+4〜5モジュール(fetcher/parser/config/例外)とテスト一式。既存パターン(frozen dataclass・独自例外・日本語テスト名)の踏襲で実装方針は明確だが、リトライ×レート制限の相互作用やモック方式(HTTPスタブ)のテスト設計に一定の工数がかかる
- **Risk: Low** — 枯れた技術(requests/BS4想定)・明確なスコープ・確立済みの統合先(`common`部品)。未知数はライブラリ選定と設定テーブル設計に限られ、いずれも設計フェーズで解消可能

## Recommendations for Design Phase

### 確定事項(ユーザー決定)

- **ライブラリ**: requests + BeautifulSoup を採用する(httpx・Scrapyは不採用)。tech.mdの「BeautifulSoup/Scrapy使い分け検討中」は本決定で解消し、steeringへの反映は設計フェーズで行う
- **実装アプローチ**: Option B(新規`src/roadstop_scraper/scraping/`パッケージ)を採用する。pyproject設定読み込みもOption Cは採らず`scraping/`パッケージ内に配置する(05/06に需要が生じた時点で`common/`への昇格を再検討)

**設計フェーズへ持ち越す Research Needed**:

1. **BeautifulSoupのパーサバックエンド**(`html.parser`(依存追加なし) vs `lxml`(高速・寛容))の決定
2. **リトライ待機(2.5)と`RateLimiter`最小間隔(1.3)の関係整理**(リトライバックオフを別枠にするか、レート制御の待機で兼ねるか)
3. **pyproject設定のテーブル名・探索方式**(`[tool.roadstop_scraper.scraping]`等の命名、`python_util`方式(cwd上方探索+不正時フォールバック)の踏襲可否)
4. **抽出結果の受け渡し形式**(Requirement 6): 汎用dict vs 型付きレコードの選択と、必須/任意セレクタ指定APIの形(構造変化検知(4.1)の「抽出必須」指定と一体で設計する)
5. **レジューム状態の形状**(処理済みURL集合の持ち方・`ResumeStore`のキー設計)と、05/06から見た利用手順の定義
6. **対象サイトの文字エンコーディング実態**(1.4): 対象4サイトのcharset確認(requestsの`charset_normalizer`で賄えるかの確認を含む。実装時のフィクスチャ設計にも影響)
