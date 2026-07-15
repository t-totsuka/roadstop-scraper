"""HtmlPage/parse_htmlのユニットテスト。

インラインのフィクスチャHTML文字列を用い、任意取得(find_*)・必須取得
(require_*)双方の欠損判別・エラー送出・警告ログを検証する(design.mdの
テスト方針に準拠し、外部フィクスチャファイルは導入しない)。
"""

from __future__ import annotations

import logging

import pytest

from roadstop_scraper.scraping.errors import StructureChangedError
from roadstop_scraper.scraping.parser import HtmlPage, parse_html

_LOGGER_NAME = "roadstop_scraper.scraping.parser"

_FIXTURE_HTML = """
<html>
  <body>
    <h1 id="title">  施設名  </h1>
    <p class="item">項目1</p>
    <p class="item">項目2</p>
    <p class="item">  項目3  </p>
    <a id="link" href="  https://example.com/detail  ">詳細</a>
    <span id="empty-text">   </span>
    <span id="empty-attr" data-value="   "></span>
  </body>
</html>
"""


def _page(url: str = "https://example.com/page") -> HtmlPage:
    return parse_html(_FIXTURE_HTML, url)


def test_find_textの検証_要素が存在する場合_トリム済みテキストを返す():
    page = _page()

    assert page.find_text("#title") == "施設名"


def test_find_attrの検証_属性が存在する場合_トリム済み属性値を返す():
    page = _page()

    assert page.find_attr("#link", "href") == "https://example.com/detail"


def test_find_textの検証_要素が存在しない場合_Noneを返す():
    page = _page()

    assert page.find_text("#not-exist") is None


def test_find_attrの検証_要素が存在しない場合_Noneを返す():
    page = _page()

    assert page.find_attr("#not-exist", "href") is None


def test_find_attrの検証_要素は存在するが属性が存在しない場合_Noneを返す():
    page = _page()

    assert page.find_attr("#title", "href") is None


def test_find_attrの検証_class等の多値属性の場合_空白区切りのstrとして結合して返す():
    # bs4はclass等の多値属性をlist[str]として返すため、str|Noneの契約を
    # 維持するために空白区切りで結合していることを確認する。
    page = parse_html('<div id="multi" class="foo bar"></div>', "https://example.com/multi")

    assert page.find_attr("#multi", "class") == "foo bar"


def test_find_textsの検証_複数要素が一致する場合_トリム済みテキストのリストを返す():
    page = _page()

    assert page.find_texts(".item") == ["項目1", "項目2", "項目3"]


def test_find_textsの検証_一致する要素がない場合_空リストを返す():
    page = _page()

    assert page.find_texts(".not-exist") == []


def test_find_attrsの検証_複数要素が一致する場合_DOM順の属性値リストを返す():
    page = parse_html(
        """
        <html><body>
          <div class="box" data-lat="35.1">A</div>
          <div class="box" data-lat="35.2">B</div>
          <div class="box" data-lat="35.3">C</div>
        </body></html>
        """,
        "https://example.com/list",
    )

    assert page.find_attrs(".box", "data-lat") == ["35.1", "35.2", "35.3"]


def test_find_attrsの検証_一部要素で属性が欠落している場合_その位置にNoneが入り件数は要素数と一致する():
    page = parse_html(
        """
        <html><body>
          <div class="box" data-lat="35.1">A</div>
          <div class="box">B</div>
          <div class="box" data-lat="35.3">C</div>
        </body></html>
        """,
        "https://example.com/list",
    )

    assert page.find_attrs(".box", "data-lat") == ["35.1", None, "35.3"]


def test_find_attrsの検証_一致する要素がない場合_空リストを返す():
    page = _page()

    assert page.find_attrs(".not-exist", "data-lat") == []


def test_find_attrsの検証_class等の多値属性の場合_空白区切りのstrとして結合して返す():
    page = parse_html(
        """
        <html><body>
          <div class="foo bar"></div>
          <div class="baz"></div>
        </body></html>
        """,
        "https://example.com/multi",
    )

    assert page.find_attrs("div", "class") == ["foo bar", "baz"]


def test_find_textの検証_要素は存在するがテキストが空白のみの場合_Noneではなく空文字を返す():
    page = _page()

    # find_*は「要素が存在するが空」と「要素が存在しない」を区別する:
    # 前者は空文字、後者はNone。空文字as欠損はrequire_*だけの概念。
    result = page.find_text("#empty-text")

    assert result == ""
    assert result is not None


def test_find_attrの検証_属性は存在するが値が空白のみの場合_Noneではなく空文字を返す():
    page = _page()

    result = page.find_attr("#empty-attr", "data-value")

    assert result == ""
    assert result is not None


def test_require_textの検証_要素が存在し非空の場合_トリム済みテキストを返し例外を送出しない():
    page = _page()

    assert page.require_text("#title") == "施設名"


def test_require_attrの検証_属性が存在し非空の場合_トリム済み属性値を返し例外を送出しない():
    page = _page()

    assert page.require_attr("#link", "href") == "https://example.com/detail"


def test_require_textの検証_要素が存在しない場合_StructureChangedErrorを送出しWARNINGログを記録する(caplog):
    page = _page(url="https://example.com/missing")

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        with pytest.raises(StructureChangedError) as exc_info:
            page.require_text("#not-exist")

    assert exc_info.value.url == "https://example.com/missing"
    assert exc_info.value.selector == "#not-exist"
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    message = warning_records[0].getMessage()
    assert "https://example.com/missing" in message
    assert "#not-exist" in message


def test_require_attrの検証_要素が存在しない場合_StructureChangedErrorを送出しWARNINGログを記録する(caplog):
    page = _page(url="https://example.com/missing")

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        with pytest.raises(StructureChangedError) as exc_info:
            page.require_attr("#not-exist", "href")

    assert exc_info.value.url == "https://example.com/missing"
    assert exc_info.value.selector == "#not-exist"
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1


def test_require_textの検証_要素は存在するがトリム後空文字の場合_StructureChangedErrorを送出しWARNINGログを記録する(
    caplog,
):
    page = _page(url="https://example.com/empty-text")

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        with pytest.raises(StructureChangedError) as exc_info:
            page.require_text("#empty-text")

    assert exc_info.value.url == "https://example.com/empty-text"
    assert exc_info.value.selector == "#empty-text"
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1


def test_require_attrの検証_属性は存在するがトリム後空文字の場合_StructureChangedErrorを送出しWARNINGログを記録する(
    caplog,
):
    page = _page(url="https://example.com/empty-attr")

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        with pytest.raises(StructureChangedError) as exc_info:
            page.require_attr("#empty-attr", "data-value")

    assert exc_info.value.url == "https://example.com/empty-attr"
    assert exc_info.value.selector == "#empty-attr"
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1


def test_HtmlPageの検証_urlはparse_htmlに渡した値がそのまま保持される():
    page = parse_html("<html></html>", "https://example.com/carrier")

    assert page.url == "https://example.com/carrier"


def test_bs4非露出の検証_findとrequireの戻り値は素のstr_list_Noneであるためbs4型のimportなしに利用できる():
    # bs4のTag/BeautifulSoupをテストコード側で一切importせず、返り値の型のみで
    # 検証する。これにより公開APIがbs4の実装詳細を露出していないことを示す。
    page = _page()

    assert isinstance(page.find_text("#title"), str)
    assert page.find_text("#not-exist") is None
    assert isinstance(page.find_texts(".item"), list)
    assert all(isinstance(item, str) for item in page.find_texts(".item"))
    assert isinstance(page.find_attr("#link", "href"), str)
    assert isinstance(page.require_text("#title"), str)
    assert isinstance(page.require_attr("#link", "href"), str)
