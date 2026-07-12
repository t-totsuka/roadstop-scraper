from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from roadstop_scraper.common import index_store
from roadstop_scraper.common.index_store import (
    IndexData,
    IndexEntry,
    IndexFileCorruptedError,
)

JST = timezone(timedelta(hours=9))


def _dt(day: int = 1) -> datetime:
    return datetime(2026, 7, day, 12, 0, 0, tzinfo=JST)


def test_読み込みの検証_index_jsonが存在しない場合_空のIndexDataを返す(tmp_path: Path):
    index = index_store.load_index(tmp_path / "index.json")

    assert index == IndexData(files=())


def test_読み込みの検証_有効なindex_jsonが存在する場合_登録済み一覧を返す(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text(
        '{"files": [{"path": "01.geojson", "updated_at": "2026-07-01T12:00:00+09:00"}]}',
        encoding="utf-8",
    )

    index = index_store.load_index(index_path)

    assert index.files == (IndexEntry(path="01.geojson", updated_at=_dt(1)),)


def test_読み込みの検証_JSON構文が不正な場合_IndexFileCorruptedErrorを送出する(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(IndexFileCorruptedError):
        index_store.load_index(index_path)


def test_読み込みの検証_ルートがオブジェクトでない場合_IndexFileCorruptedErrorを送出する(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text("[]", encoding="utf-8")

    with pytest.raises(IndexFileCorruptedError):
        index_store.load_index(index_path)


def test_読み込みの検証_エントリがオブジェクトでない場合_IndexFileCorruptedErrorを送出する(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text('{"files": ["not-an-object"]}', encoding="utf-8")

    with pytest.raises(IndexFileCorruptedError):
        index_store.load_index(index_path)


def test_読み込みの検証_filesが非リストの場合_IndexFileCorruptedErrorを送出する(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text('{"files": {}}', encoding="utf-8")

    with pytest.raises(IndexFileCorruptedError):
        index_store.load_index(index_path)


def test_読み込みの検証_エントリのpathが欠落している場合_IndexFileCorruptedErrorを送出する(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text(
        '{"files": [{"updated_at": "2026-07-01T12:00:00+09:00"}]}', encoding="utf-8"
    )

    with pytest.raises(IndexFileCorruptedError):
        index_store.load_index(index_path)


def test_読み込みの検証_エントリのupdated_atが欠落している場合_IndexFileCorruptedErrorを送出する(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text('{"files": [{"path": "01.geojson"}]}', encoding="utf-8")

    with pytest.raises(IndexFileCorruptedError):
        index_store.load_index(index_path)


def test_読み込みの検証_updated_atがパース不能な文字列の場合_IndexFileCorruptedErrorを送出する(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text(
        '{"files": [{"path": "01.geojson", "updated_at": "not-a-date"}]}',
        encoding="utf-8",
    )

    with pytest.raises(IndexFileCorruptedError):
        index_store.load_index(index_path)


def test_更新の検証_未登録pathの場合_新規エントリとして追加する():
    index = IndexData(files=())

    updated = index_store.upsert_entry(index, "01.geojson", _dt(1))

    assert updated.files == (IndexEntry(path="01.geojson", updated_at=_dt(1)),)


def test_更新の検証_登録済みpathの場合_updated_atを更新する():
    index = IndexData(files=(IndexEntry(path="01.geojson", updated_at=_dt(1)),))

    updated = index_store.upsert_entry(index, "01.geojson", _dt(2))

    assert updated.files == (IndexEntry(path="01.geojson", updated_at=_dt(2)),)


def test_更新の検証_upsert後も元のIndexDataは変更されない():
    original = IndexData(files=(IndexEntry(path="01.geojson", updated_at=_dt(1)),))

    index_store.upsert_entry(original, "02.geojson", _dt(2))

    assert original.files == (IndexEntry(path="01.geojson", updated_at=_dt(1)),)


def test_保存の検証_updated_atがISO8601形式でシリアライズされる(tmp_path: Path):
    import json

    index_path = tmp_path / "index.json"
    index = IndexData(files=(IndexEntry(path="01.geojson", updated_at=_dt(1)),))

    index_store.save_index(index, index_path)

    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert data["files"][0]["path"] == "01.geojson"
    assert data["files"][0]["updated_at"] == "2026-07-01T12:00:00+09:00"


def test_往復の検証_保存して再読み込みするとデータが一致する(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index = IndexData(
        files=(
            IndexEntry(path="01.geojson", updated_at=_dt(1)),
            IndexEntry(path="02.geojson", updated_at=_dt(2)),
        )
    )

    index_store.save_index(index, index_path)
    reloaded = index_store.load_index(index_path)

    assert reloaded == index
