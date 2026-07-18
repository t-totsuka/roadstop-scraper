"""URL単位の処理済み集合を``ResumeStore``へ永続化するレジューム管理。

呼び出し側(05-michinoeki-scraping・06-sapa-scraping)は、対象サイト単位の
キー(例: ``michinoeki``)で``UrlResumeTracker``を生成し、連続取得中に
処理済みURLの判定・記録を行う。永続化・破損時復旧そのものは``ResumeStore``
の契約に委譲し、本モジュールはURL集合としての意味付けのみを担う。
"""

from __future__ import annotations

from roadstop_scraper.common.resume_store import ResumeStore

__all__ = ["UrlResumeTracker"]

_STATE_KEY = "processed_urls"


class UrlResumeTracker:
    """処理済みURL集合を``ResumeStore``に永続化し、スキップ判定を提供する。"""

    def __init__(self, key: str, store: ResumeStore | None = None) -> None:
        """``key``に対応する状態を``store``から復元する(既定は新規``ResumeStore``)。

        状態が存在しない・破損している場合(``ResumeStore.load``が``None``を
        返す場合)は空集合から開始する。
        """
        self._key = key
        self._store = store if store is not None else ResumeStore()

        saved_state = self._store.load(self._key)
        if saved_state is None:
            self._processed_urls: set[str] = set()
        else:
            self._processed_urls = set(saved_state.get(_STATE_KEY, []))

    def is_processed(self, url: str) -> bool:
        """``url``が処理済み集合に含まれるかをO(1)で判定する。"""
        return url in self._processed_urls

    def mark_processed(self, url: str) -> None:
        """``url``を処理済み集合へ追加し、呼び出しの都度、状態全体を永続化する。"""
        self._processed_urls.add(url)
        self._persist()

    def clear(self) -> None:
        """処理済み集合を空にし、永続化された状態も``ResumeStore``経由で削除する。"""
        self._processed_urls.clear()
        self._store.clear(self._key)

    def _persist(self) -> None:
        """現在の処理済み集合の全体を``ResumeStore``へ保存する。"""
        self._store.save(self._key, {_STATE_KEY: sorted(self._processed_urls)})
