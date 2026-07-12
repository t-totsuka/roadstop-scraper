"""``geo-json/index.json`` の読み込み・更新・保存。

各GeoJSONファイルの ``path`` と ``updated_at`` を保持する管理ファイルを、
不正データを検知しつつ一貫した方法で読み書きする。メモリ上の ``IndexData``
は不変(immutable)で、更新のたびに新しいインスタンスを生成する。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

__all__ = [
    "IndexEntry",
    "IndexData",
    "IndexFileCorruptedError",
    "load_index",
    "upsert_entry",
    "save_index",
]


@dataclass(frozen=True)
class IndexEntry:
    """``index.json`` の1エントリ(GeoJSONファイル1件分)。"""

    path: str
    updated_at: datetime


@dataclass(frozen=True)
class IndexData:
    """``index.json`` 全体の不変表現。"""

    files: tuple[IndexEntry, ...]


class IndexFileCorruptedError(ValueError):
    """``index.json`` がJSON構文または構造として不正な場合に送出される。"""


def load_index(index_path: Path) -> IndexData:
    """``index.json`` を読み込み ``IndexData`` として返す。

    ファイルが存在しない場合は空の ``IndexData`` を返す。JSON構文エラーや
    期待する構造を満たさない場合は、いずれも :class:`IndexFileCorruptedError`
    に正規化して送出する(既存データは破壊しない)。
    """
    if not index_path.exists():
        return IndexData(files=())

    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise IndexFileCorruptedError(
            f"index.jsonのJSON構文が不正です: {index_path}"
        ) from error

    return _parse_index(raw, index_path)


def _parse_index(raw: object, index_path: Path) -> IndexData:
    """デシリアライズ済みのオブジェクトを検証して ``IndexData`` に変換する。"""
    if not isinstance(raw, dict):
        raise IndexFileCorruptedError(f"index.jsonのルートがオブジェクトではありません: {index_path}")

    files = raw.get("files")
    if not isinstance(files, list):
        raise IndexFileCorruptedError(f"index.jsonのfilesがリストではありません: {index_path}")

    entries: list[IndexEntry] = []
    for item in files:
        entries.append(_parse_entry(item, index_path))
    return IndexData(files=tuple(entries))


def _parse_entry(item: object, index_path: Path) -> IndexEntry:
    """1エントリ分の辞書を検証して ``IndexEntry`` に変換する。"""
    if not isinstance(item, dict):
        raise IndexFileCorruptedError(f"index.jsonのエントリがオブジェクトではありません: {index_path}")

    path = item.get("path")
    updated_at_raw = item.get("updated_at")
    if not isinstance(path, str) or not isinstance(updated_at_raw, str):
        raise IndexFileCorruptedError(
            f"index.jsonのエントリにpath/updated_atが不足しています: {index_path}"
        )

    try:
        updated_at = datetime.fromisoformat(updated_at_raw)
    except ValueError as error:
        raise IndexFileCorruptedError(
            f"index.jsonのupdated_atが日時としてパースできません: {updated_at_raw}"
        ) from error

    return IndexEntry(path=path, updated_at=updated_at)


def upsert_entry(index: IndexData, path: str, updated_at: datetime) -> IndexData:
    """指定 ``path`` のエントリを更新(未登録なら追加)した新しい ``IndexData`` を返す。

    入力の ``index`` は変更しない。同一 ``path`` のエントリは常に1件に保たれる。
    """
    updated_entries: list[IndexEntry] = []
    replaced = False
    for entry in index.files:
        if entry.path == path:
            updated_entries.append(replace(entry, updated_at=updated_at))
            replaced = True
        else:
            updated_entries.append(entry)

    if not replaced:
        updated_entries.append(IndexEntry(path=path, updated_at=updated_at))

    return IndexData(files=tuple(updated_entries))


def save_index(index: IndexData, index_path: Path) -> None:
    """``IndexData`` を ``index.json`` へJSONとして書き込み永続化する。

    ``updated_at`` はISO 8601形式(``isoformat()``)でシリアライズする。
    """
    payload = {
        "files": [
            {"path": entry.path, "updated_at": entry.updated_at.isoformat()}
            for entry in index.files
        ]
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
