"""一時ファイル経由でのアトミックなテキストファイル書き込み(パッケージ内部用)。

書き込み先と同一ディレクトリに一時ファイルを作成して内容を書き込み、
``os.replace`` による原子的なリネームで置き換える。書き込み途中でプロセスが
停止しても、部分書き込みは一時ファイル側にのみ発生し、既存ファイルが
破損した状態で残ることはない。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["write_text_atomic"]


def write_text_atomic(path: Path, content: str, encoding: str = "utf-8") -> None:
    """``content`` を ``path`` へアトミックに書き込む。

    親ディレクトリは呼び出し側が事前に作成しておく必要がある。書き込み・
    置き換えに失敗した場合は一時ファイルを削除して例外を再送出し、
    既存ファイルは元の内容のまま保たれる。
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as tmp_file:
            tmp_file.write(content)
        # mkstempの一時ファイルは0600で作成されるため、通常のファイル作成と
        # 同じ権限(0666からumaskを引いたもの)に合わせてから置き換える
        current_umask = os.umask(0)
        os.umask(current_umask)
        os.chmod(tmp_name, 0o666 & ~current_umask)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
