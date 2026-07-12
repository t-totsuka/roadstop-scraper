"""スクレイピング進捗状態のキー単位での永続化・復元・クリア。

呼び出し側が指定するキーごとに、進捗状態(JSONシリアライズ可能な ``dict``)を
``DEFAULT_STATE_DIR``(既定値 ``.resume/``)配下の ``<key>.json`` として永続化する。
未保存キーの読み込みは ``None`` を返し、呼び出し側の「最初から開始」判断に使う。
排他制御は行わず、単一プロセスでの逐次実行を前提とする。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_STATE_DIR", "ResumeStore"]

DEFAULT_STATE_DIR: Path = Path(".resume")


class ResumeStore:
    """進捗状態をキー単位で永続化・復元・クリアするストア。"""

    def __init__(self, state_dir: Path = DEFAULT_STATE_DIR) -> None:
        """状態の保存先ディレクトリを受け取る(既定値は ``.resume/``)。"""
        self._state_dir = state_dir

    def save(self, key: str, state: dict[str, Any]) -> None:
        """指定キーの進捗状態を ``<state_dir>/<key>.json`` として保存する。

        保存先ディレクトリが存在しなければ作成し、対象ファイルの全体を都度上書きする。
        """
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._path_for(key).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def load(self, key: str) -> dict[str, Any] | None:
        """指定キーの進捗状態を読み込む。未保存なら ``None`` を返す。"""
        path = self._path_for(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def clear(self, key: str) -> None:
        """指定キーの永続化状態を削除する(未保存キーでもエラーにしない)。"""
        self._path_for(key).unlink(missing_ok=True)

    def _path_for(self, key: str) -> Path:
        """キーに対応する状態ファイルのパスを返す。"""
        return self._state_dir / f"{key}.json"
