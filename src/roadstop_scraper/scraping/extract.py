"""抽出項目の宣言的な受け渡し(FieldSpec/ExtractedRecord/extract_record)。

抽出項目の並び(``FieldSpec``)を受け取り、``HtmlPage``の任意/必須取得手段を
適用して構造化されたレコード(``ExtractedRecord``)を生成する。項目名の意味
(name・tel等)は解釈せず、``FacilityProperties``へのマッピング・値の正規化は
05/06の責務とする(6.1)。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from roadstop_scraper.common.logging_setup import get_logger
from roadstop_scraper.scraping.parser import HtmlPage

__all__ = ["ExtractedRecord", "FieldSpec", "extract_record"]

_logger = get_logger(__name__)


@dataclass(frozen=True)
class FieldSpec:
    """抽出項目の宣言。項目名・セレクタ・属性・必須有無からなる。"""

    name: str
    """レコード上の項目名(呼び出し側が定義)。"""

    selector: str
    """CSSセレクタ。"""

    attribute: str | None = None
    """Noneならテキストを、指定時はその属性値を抽出する。"""

    required: bool = False
    """Trueの場合、欠落時にStructureChangedErrorを送出する。"""


@dataclass(frozen=True)
class ExtractedRecord:
    """抽出結果の構造化レコード。"""

    source_url: str
    """取得元URL(6.2)。"""

    values: Mapping[str, str | None]
    """項目名→値。任意項目の欠損はキーを保持したまま値をNoneにする(6.3)。"""


def extract_record(page: HtmlPage, specs: Sequence[FieldSpec]) -> ExtractedRecord:
    """FieldSpecの並びに従いHtmlPageから値を取り出し、ExtractedRecordを生成する。

    specsのnameが重複する場合はpageへ一切アクセスせずValueErrorを送出する
    (fail fast)。必須項目(required=True)が1つでも欠落すると、内部で呼び出す
    HtmlPage.require_*からStructureChangedErrorが送出され、そのまま呼び出し側
    へ伝播する(レコードは返さない)。任意項目の欠損はキー自体を保持したまま
    値のみNoneにする。全値がNoneのレコードが生成された場合は防御としてWARNING
    ログを記録する(運用規約: specsには最低1つrequired=Trueの項目を含めること
    が期待されるが、この関数自体はそれを強制しない)。
    """
    _reject_duplicate_names(specs)

    values: dict[str, str | None] = {spec.name: _extract_one(page, spec) for spec in specs}

    if values and all(value is None for value in values.values()):
        _logger.warning("全抽出項目が欠損したレコードを検知: url=%s", page.url)

    return ExtractedRecord(source_url=page.url, values=values)


def _reject_duplicate_names(specs: Sequence[FieldSpec]) -> None:
    """specs内でnameが重複する場合、pageへアクセスする前にValueErrorを送出する。"""
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            raise ValueError(f"抽出項目名 '{spec.name}' が重複しています")
        seen.add(spec.name)


def _extract_one(page: HtmlPage, spec: FieldSpec) -> str | None:
    """単一のFieldSpecに対し、attribute/requiredの組み合わせに応じたHtmlPageのAPIを呼び出す。"""
    if spec.attribute is None:
        return page.require_text(spec.selector) if spec.required else page.find_text(spec.selector)
    return (
        page.require_attr(spec.selector, spec.attribute)
        if spec.required
        else page.find_attr(spec.selector, spec.attribute)
    )
