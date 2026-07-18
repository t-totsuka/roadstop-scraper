"""FieldSpec/ExtractedRecord/extract_recordのユニットテスト。

実際のparse_html()で生成したHtmlPageを用い(HtmlPage自体はfakeにしない)、
必須/任意混在の抽出項目からのレコード生成・欠損判別・必須欠落時の
StructureChangedError伝播・name重複時の早期ValueError・全項目欠損時の
WARNINGログを検証する(design.mdのテスト方針に準拠)。
"""

from __future__ import annotations

import logging

import pytest

from roadstop_scraper.scraping.errors import StructureChangedError
from roadstop_scraper.scraping.extract import ExtractedRecord, FieldSpec, extract_record
from roadstop_scraper.scraping.parser import parse_html

_LOGGER_NAME = "roadstop_scraper.scraping.extract"

_FIXTURE_HTML = """
<html>
  <body>
    <h1 id="name">  施設 太郎  </h1>
    <p id="tel">03-1234-5678</p>
    <a id="link" href="  https://example.com/detail  ">詳細</a>
  </body>
</html>
"""


def _page(url: str = "https://example.com/page"):
    return parse_html(_FIXTURE_HTML, url)


def test_extract_recordの検証_必須任意混在のFieldSpecで全項目が存在する場合_全項目名をキーに持つレコードを生成する():
    page = _page()
    specs = [
        FieldSpec(name="name", selector="#name", required=True),
        FieldSpec(name="tel", selector="#tel", required=False),
        FieldSpec(name="url", selector="#link", attribute="href", required=False),
    ]

    record = extract_record(page, specs)

    assert isinstance(record, ExtractedRecord)
    assert record.values == {
        "name": "施設 太郎",
        "tel": "03-1234-5678",
        "url": "https://example.com/detail",
    }


def test_extract_recordの検証_任意項目のセレクタが一致しない場合_該当キーはNoneでレコードを返す():
    page = _page()
    specs = [
        FieldSpec(name="name", selector="#name", required=True),
        FieldSpec(name="fax", selector="#not-exist", required=False),
    ]

    record = extract_record(page, specs)

    # 欠損項目もキー自体は保持し、値のみNoneになることを確認する。
    assert "fax" in record.values
    assert record.values["fax"] is None
    assert record.values["name"] == "施設 太郎"


def test_extract_recordの検証_必須項目のセレクタが一致しない場合_StructureChangedErrorを送出しレコードを返さない():
    page = _page(url="https://example.com/missing")
    specs = [
        FieldSpec(name="name", selector="#not-exist", required=True),
        FieldSpec(name="tel", selector="#tel", required=False),
    ]

    with pytest.raises(StructureChangedError) as exc_info:
        extract_record(page, specs)

    assert exc_info.value.url == "https://example.com/missing"
    assert exc_info.value.selector == "#not-exist"


def test_extract_recordの検証_attribute指定の必須項目が存在する場合_属性値を取得したレコードを返す():
    page = _page()
    specs = [FieldSpec(name="url", selector="#link", attribute="href", required=True)]

    record = extract_record(page, specs)

    assert record.values == {"url": "https://example.com/detail"}


def test_extract_recordの検証_attribute指定の任意項目が存在しない場合_該当キーはNoneになる():
    page = _page()
    specs = [FieldSpec(name="og_image", selector="#not-exist", attribute="content", required=False)]

    record = extract_record(page, specs)

    assert record.values == {"og_image": None}


def test_extract_recordの検証_attribute指定の必須項目が存在しない場合_StructureChangedErrorを送出する():
    page = _page(url="https://example.com/missing-attr")
    specs = [FieldSpec(name="url", selector="#not-exist", attribute="href", required=True)]

    with pytest.raises(StructureChangedError) as exc_info:
        extract_record(page, specs)

    assert exc_info.value.selector == "#not-exist"


def test_extract_recordの検証_項目名が重複する場合_ValueErrorを送出しpageに一切アクセスしない(monkeypatch):
    page = _page(url="https://example.com/dup")
    # find_*/require_*をすべて「呼ばれたら失敗」に差し替え、重複検証が
    # pageへのアクセスより先に行われる(fail fast)ことを証明する。
    for method_name in ("find_text", "find_attr", "require_text", "require_attr"):

        def _fail(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("pageのメソッドが呼び出されました(fail fastに違反)")

        monkeypatch.setattr(page, method_name, _fail)
    specs = [
        FieldSpec(name="name", selector="#a", required=True),
        FieldSpec(name="name", selector="#b", required=False),
    ]

    with pytest.raises(ValueError):
        extract_record(page, specs)


def test_extract_recordの検証_生成したレコードのsource_urlはpageのurlと一致する():
    page = _page(url="https://example.com/carrier")
    specs = [FieldSpec(name="name", selector="#name", required=True)]

    record = extract_record(page, specs)

    assert record.source_url == "https://example.com/carrier"


def test_extract_recordの検証_全項目が欠損したレコードが生成された場合_対象URL付きでWARNINGログを出す(caplog):
    page = _page(url="https://example.com/all-missing")
    specs = [
        FieldSpec(name="name", selector="#not-exist-1", required=False),
        FieldSpec(name="tel", selector="#not-exist-2", required=False),
    ]

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        record = extract_record(page, specs)

    assert record.values == {"name": None, "tel": None}
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "https://example.com/all-missing" in warning_records[0].getMessage()
