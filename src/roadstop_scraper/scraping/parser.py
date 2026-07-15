"""BeautifulSoupを隠蔽したHTML構造抽出(HtmlPage)。

CSSセレクタによる任意取得(``find_*``)・必須取得(``require_*``)の2系統の
抽出APIを提供する。bs4の型(``Tag``・``BeautifulSoup``等)は本モジュール内に
閉じ、呼び出し側のシグネチャには一切現れない(3.3)。
"""

from __future__ import annotations

from typing import NoReturn

from bs4 import BeautifulSoup

from roadstop_scraper.common.logging_setup import get_logger
from roadstop_scraper.scraping.errors import StructureChangedError

__all__ = ["HtmlPage", "parse_html"]

_logger = get_logger(__name__)


def parse_html(text: str, url: str) -> HtmlPage:
    """HTML文字列を解析し、要素抽出可能な :class:`HtmlPage` を返す(3.1)。

    バックエンドは標準ライブラリのみで動く``html.parser``を用いる(追加依存なし)。
    ``html.parser``は壊れたHTMLも寛容に解析するため、パース自体が例外を送出する
    ことは実質的にない。パース結果が空文書になる場合の検知は後続の``require_*``
    に委ねる(3.4)。
    """
    soup = BeautifulSoup(text, "html.parser")
    return HtmlPage(soup, url)


class HtmlPage:
    """bs4を隠蔽した、セレクタベースの任意/必須抽出APIを提供するパース結果。"""

    url: str
    """取得元URL(エラー・レコードへの引き回し用)。"""

    def __init__(self, soup: BeautifulSoup, url: str) -> None:
        self.url = url
        self._soup = soup

    def find_text(self, selector: str) -> str | None:
        """任意取得: セレクタに一致する最初の要素のトリム済みテキストを返す。

        要素が存在しない場合は``None``を返す(6.3の欠損判別に対応)。要素が
        存在するがテキストが空(トリム後に空文字)の場合は、要素が存在する
        事実自体は分かっているため空文字をそのまま返す(``None``にはしない)。
        セレクタ構文が不正な場合はbs4の例外をそのまま伝播させる(隠蔽しない)。
        """
        element = self._soup.select_one(selector)
        if element is None:
            return None
        return element.get_text().strip()

    def find_texts(self, selector: str) -> list[str]:
        """任意取得: セレクタに一致する全要素のトリム済みテキストのリストを返す。

        一致する要素がなければ空リストを返す。
        """
        return [element.get_text().strip() for element in self._soup.select(selector)]

    def find_attr(self, selector: str, attribute: str) -> str | None:
        """任意取得: セレクタに一致する最初の要素の、指定属性のトリム済み値を返す。

        要素が存在しない、または属性自体が存在しない場合は``None``を返す。
        """
        element = self._soup.select_one(selector)
        if element is None:
            return None
        value = element.get(attribute)
        if value is None:
            return None
        if isinstance(value, list):
            # class等の多値属性はbs4がlist[str]を返すため、空白区切りで結合する
            value = " ".join(value)
        return value.strip()

    def find_attrs(self, selector: str, attribute: str) -> list[str | None]:
        """任意取得: セレクタに一致する全要素の、指定属性のトリム済み値をDOM順のリストで返す。

        ``find_texts``の属性版。各要素について、指定属性が存在しなければ
        当該位置に``None``を入れる(要素をスキップせず、リスト長を一致する
        要素数と揃える)。呼び出し側が複数属性を同一インデックスで相関させる
        ことを想定するため、欠損を理由に位置をずらしてはならない。
        一致する要素がなければ空リストを返す。
        """
        results: list[str | None] = []
        for element in self._soup.select(selector):
            value = element.get(attribute)
            if value is None:
                results.append(None)
                continue
            if isinstance(value, list):
                # class等の多値属性はbs4がlist[str]を返すため、空白区切りで結合する
                value = " ".join(value)
            results.append(value.strip())
        return results

    def require_text(self, selector: str) -> str:
        """必須取得: セレクタに一致する最初の要素のトリム済みテキストを返す。

        要素自体が存在しない場合に加え、要素はあってもトリム後のテキストが
        空文字である場合も欠落として扱い(4.1と同一視)、WARNINGログを記録した
        上で :class:`StructureChangedError` を送出する(4.2、4.3)。
        """
        value = self.find_text(selector)
        if not value:
            self._log_and_raise(selector)
        return value

    def require_attr(self, selector: str, attribute: str) -> str:
        """必須取得: セレクタに一致する最初の要素の、指定属性のトリム済み値を返す。

        要素・属性自体が存在しない場合に加え、値がトリム後に空文字である
        場合も欠落として扱い、WARNINGログを記録した上で
        :class:`StructureChangedError` を送出する(4.1、4.2、4.3)。
        """
        value = self.find_attr(selector, attribute)
        if not value:
            self._log_and_raise(selector)
        return value

    def _log_and_raise(self, selector: str) -> NoReturn:
        """構造変化検知のWARNINGログを記録し、StructureChangedErrorを送出する。"""
        _logger.warning("HTML構造変化を検知: url=%s selector=%s", self.url, selector)
        raise StructureChangedError(self.url, selector)
