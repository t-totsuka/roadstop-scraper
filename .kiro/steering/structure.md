# Project Structure

## Organization Philosophy

Pythonの標準的なプロジェクト構成を基本とする。スクレイピング結果とテスト成果物は、ソースコードから明確に分離したフォルダに出力する。

## Directory Patterns

### スクレイピング結果

**Location**: `/geo-json/`
**Purpose**: スクレイピングした道の駅・SA/PA情報をGeoJSON形式で出力・格納する。1ファイルへの集約はサイズ肥大化を招くため、都道府県単位でファイルを分割する
**Example**:

```text
geo-json/
├── 01_hokkaido_michinoeki.geojson
├── 01_hokkaido_sapa.geojson
├── 08_ibaraki_michinoeki.geojson
├── 08_ibaraki_sapa.geojson
└── index.json
```

分割された各ファイルを管理するため、`geo-json/index.json` に更新日時とファイルパスの一覧を持たせる:

```json
{
  "files": [
    {
      "path": "01_hokkaido_michinoeki.geojson",
      "updated_at": "2026-07-12T09:00:00+09:00"
    },
    {
      "path": "08_ibaraki_sapa.geojson",
      "updated_at": "2026-07-12T09:05:00+09:00"
    }
  ]
}
```

### カバレッジレポート

**Location**: `/report/`
**Purpose**: テスト実行時のHTMLカバレッジレポート出力先。git管理対象外(`.gitignore`に追加)
**Example**: `report/index.html`

## Naming Conventions

- **テスト関数**: 日本語ベースで `test_(テスト目的)_(テスト対象)が_(状態)だった場合_(想定される結果)` の形式に従う
- **GeoJSONファイル**: `(都道府県番号2桁)_(都道府県名ローマ字)_(michinoeki|sapa).geojson` の形式とする(例: `01_hokkaido_michinoeki.geojson`)。日本語は使わずローマ字表記とし、道の駅は`michinoeki`、SA/PAは`sapa`と表記する

## Code Organization Principles

- **spec単位のブランチ運用**: `.kiro/specs/` の spec ごとに git ブランチを作成し、作業内容に応じて適宜コミットする。spec が完了したら `main` ブランチへマージする
- **README更新**: タスク完了時には `README.md` を最新の状態に更新する
- **コメント方針**: コード本体はHow、テストコードはWhat、コミットログはWhy、コードコメント内のWhy notを記述する(詳細は `tech.md` 参照)

---

Document patterns, not file trees. New files following patterns shouldn't require updates.
