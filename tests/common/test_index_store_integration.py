"""``IndexStore`` の統合検証(タスク3.1)。

一時ディレクトリ上の実ファイルに対して ``load_index → upsert_entry →
save_index`` の一連の流れを実行し、生成されるJSONが ``structure.md`` 定義の
``index.json`` フォーマット(``files`` 配列、各要素が ``path`` と
``updated_at``)と一致することを確認する。個々の関数の単体挙動は
``test_index_store.py`` で検証済みのため、ここでは実ファイルを介した
フロー全体の結合を対象とする。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from python_util import time_utility
from roadstop_scraper.common import index_store


def test_統合フローの検証_ファイル不在から一連の更新を実行した場合_structure_md準拠のindex_jsonが生成される(
    tmp_path: Path,
):
    # geo-json/index.json を指す実パス(ファイルはまだ存在しない)
    index_path = tmp_path / "geo-json" / "index.json"

    # load(不在) → upsert → save の一連の流れを実行する
    index = index_store.load_index(index_path)
    index = index_store.upsert_entry(
        index, "01_hokkaido_michinoeki.geojson", time_utility.now()
    )
    index = index_store.upsert_entry(
        index, "08_ibaraki_sapa.geojson", time_utility.now()
    )
    index_store.save_index(index, index_path)

    # 生成されたJSONが structure.md 定義のフォーマットに一致することを確認する
    assert index_path.exists()
    data = json.loads(index_path.read_text(encoding="utf-8"))

    assert list(data.keys()) == ["files"]
    assert isinstance(data["files"], list)
    assert len(data["files"]) == 2
    for entry in data["files"]:
        assert set(entry.keys()) == {"path", "updated_at"}
        assert isinstance(entry["path"], str)
        # updated_at は ISO 8601(JSTオフセット付き)としてパース可能であること
        parsed = datetime.fromisoformat(entry["updated_at"])
        assert parsed.utcoffset() is not None

    paths = [entry["path"] for entry in data["files"]]
    assert paths == ["01_hokkaido_michinoeki.geojson", "08_ibaraki_sapa.geojson"]


def test_統合フローの検証_保存後に再読み込みして既存pathを更新した場合_更新が永続化される(
    tmp_path: Path,
):
    index_path = tmp_path / "geo-json" / "index.json"

    # 1回目: 新規エントリを保存する
    index = index_store.load_index(index_path)
    first_timestamp = time_utility.now()
    index = index_store.upsert_entry(
        index, "01_hokkaido_michinoeki.geojson", first_timestamp
    )
    index_store.save_index(index, index_path)

    # 2回目: 実ファイルから読み込み直し、同一 path を更新して保存する
    reloaded = index_store.load_index(index_path)
    second_timestamp = time_utility.now()
    updated = index_store.upsert_entry(
        reloaded, "01_hokkaido_michinoeki.geojson", second_timestamp
    )
    index_store.save_index(updated, index_path)

    # 再読み込みで、エントリが1件のまま最新のタイムスタンプに更新されている
    final = index_store.load_index(index_path)
    assert len(final.files) == 1
    assert final.files[0].path == "01_hokkaido_michinoeki.geojson"
    assert final.files[0].updated_at == second_timestamp
