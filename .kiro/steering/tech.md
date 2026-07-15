# Technology Stack

## Architecture

対象WebサイトへHTTPアクセスしてHTMLを取得・解析し、位置情報等を抽出してGeoJSONへ変換するバッチ型スクレイピングパイプライン。サードパーティサーバへの影響を最小化するため、リクエスト頻度制御とレジューム(再開)機構を前提にした設計とする。

## Core Technologies

- **Language**: Python
- **Package Manager**: pdm
- **Scraping**: requests + BeautifulSoup(確定)

## Key Libraries

- **requests**: HTTP取得・タイムアウト・エンコーディング解決を担う
- **BeautifulSoup**: 静的HTMLのパース・要素抽出を担う
- **python_util** ([t-totsuka/python_util](https://github.com/t-totsuka/python_util)): ログ出力を含む自作の共通ユーティリティ。git依存として導入する(`pdm add "python_util @ git+https://github.com/t-totsuka/python_util.git"`)

## Development Standards

### Lint / Format

- **ruff** を使用する

### Testing

- テスト関数名は日本語ベースの命名規則に従う:
  `test_(テスト目的)_(テスト対象)が_(状態)だった場合_(想定される結果)`
- カバレッジレポートはHTML形式で出力する

### コメント方針

それぞれの記述対象で書くべき観点を分ける:

- **コード本体のコメント**: How(どう実装しているか)
- **テストコードのコメント**: What(何を検証しているか)
- **コミットログ**: Why(なぜその変更をしたか)
- **コードコメント内のWhy not**: あえてやっていないこと・見送った選択肢とその理由

### ログ出力

動作ログの保存には `python_util.logging` の `get_logger()` を利用する:

```python
from python_util.logging import get_logger

logger = get_logger(__name__)
logger.info("スクレイピング開始")
```

- 出力先・ログレベルはコードを変更せず、呼び出し側の `pyproject.toml` の `[tool.python_util.logging]` テーブルで制御する(例: `file = "logs/app.log"` でファイル出力、`[tool.python_util.logging.loggers."<module>"]` でモジュール単位の上書き)
- 設定を省略した場合はコンソール出力のみ・レベル`INFO`がデフォルトとなる

## Development Environment

### Required Tools

- pdm(依存関係・仮想環境管理)

### Common Commands

```bash
# Install: pdm install
# Lint: pdm run ruff check .
# Test: pdm run pytest
```

## Key Technical Decisions

- **リクエスト頻度制御**: サードパーティサーバへの負荷を避けるため、スクレイピング処理には意図的なリクエスト間隔・レート制限を組み込む
- **レジューム機能**: 長時間・大量ページのスクレイピングを想定し、途中経過を保持して再実行時に続きから処理できるようにする
- **ログ出力の共通化**: 標準の`logging`を都度セットアップするのではなく、既存の`python_util.logging`を再利用する。リクエスト間隔・レジューム状況・スクレイピング失敗などの動作状況を、設定変更のみでファイル出力に切り替えられるようにするため
- **スクレイピング技術方針**: requests + BeautifulSoupに確定し、Scrapyは不採用とする(リクエスト頻度制御・レジューム機能が`common/`で既に自作実装されており、Scrapyの導入は機能重複とアーキテクチャ競合を招くため)

---

Document standards and patterns, not every dependency.
