"""SA/PAサイトアダプタの共通契約(design.md「sapa.sites」節)。

NEXCO東日本・中日本・西日本の3サイトの差異(URL構成・HTML構造・上り/下り等
の表記)を吸収するアダプタが実装すべき共通型・プロトコルと、全サイト共通の
関心事である上下線表記の正規化・名称からの方向表記除去ヘルパを提供する
(research.md「上下線・名称正規化の方針」参照: サイト固有の関心事ではないため
ここへ集約し、各アダプタから利用する)。

サイト固有のURL構成・セレクタ・パースロジックは本モジュールでは扱わない
(各アダプタ ``east``/``central``/``west`` の責務。タスク3.1-3.3で実装する)。
``ALL_SITES`` は3アダプタが揃うタスク3.4で登録するため、現時点では空。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from roadstop_scraper.geojson import Coordinate, Direction, Parking, Prefecture
from roadstop_scraper.scraping.parser import HtmlPage

__all__ = [
    "ALL_SITES",
    "SapaDetail",
    "SapaListingResult",
    "SapaSite",
    "SapaStub",
    "normalize_direction",
    "strip_direction_notation",
]

# 半角/全角の丸括弧はサイトによって混在する(NEXCO東日本は半角、中日本は全角の
# 実測例がある。research.md参照)ため、両方を等価に扱う。
_PAREN_OPEN = "[（(]"
_PAREN_CLOSE = "[）)]"
# 「上」「下」単独は施設名の一部(例: 「上尾」「上里」)と衝突しうるため、括弧で
# 囲まれている場合に限り単独表記も方向表記として受理する。括弧の外では
# 「り」+「線」または「方面」を伴う曖昧さのない表記のみを受理する。
_UP_CORE = "上(?:り)?(?:線|方面)?"
_DOWN_CORE = "下(?:り)?(?:線|方面)?"
_PARENTHESIZED_PATTERN = re.compile(rf"{_PAREN_OPEN}(?P<token>{_UP_CORE}|{_DOWN_CORE}){_PAREN_CLOSE}")
_BARE_PATTERN = re.compile(r"(?P<token>上り(?:線|方面)|下り(?:線|方面))")


def normalize_direction(text: str) -> Direction | None:
    """サイト固有の上下線表記を正規化済みの ``Direction`` へ写像する(3.2)。

    「(上)」「(上り)」「上り方面」「上り線」および全角括弧の同等表記を
    ``Direction.UP`` へ、対応する下り表記を ``Direction.DOWN`` へ正規化する。
    方向表記が含まれない場合(上下集約施設)は ``None`` を返す。
    """
    match = _PARENTHESIZED_PATTERN.search(text) or _BARE_PATTERN.search(text)
    if match is None:
        return None
    token = match.group("token")
    return Direction.UP if token.startswith("上") else Direction.DOWN


def strip_direction_notation(name: str) -> str:
    """施設の表示名から方向表記を除去した名称を返す(3.2)。

    方向表記を含まない名称はそのまま返す。除去後に生じうる連続空白は1つに
    畳み、前後の空白は取り除く(括弧除去の副作用で余分な空白・括弧が残らない
    ようにする)。
    """
    stripped = _PARENTHESIZED_PATTERN.sub("", name)
    stripped = _BARE_PATTERN.sub("", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


@dataclass(frozen=True)
class SapaStub:
    """一覧ページ上のSA/PA1件分の最小情報。詳細取得の起点となる。"""

    display_name: str
    """一覧上の表示名(方向表記を含みうる生値)。"""

    detail_url: str
    """詳細ページ絶対URL。source_url・レジューム・マージのキー。"""


@dataclass(frozen=True)
class SapaListingResult:
    """1一覧ページ(または一覧URL群)のパース結果。"""

    stubs: tuple[SapaStub, ...]
    """パースできたスタブ列。"""

    listed_urls: frozenset[str]
    """一覧で存在確認できた全detail_url(スタブ化に失敗した分も含む)。"""

    skipped_count: int
    """一覧段階で解釈できずスキップした要素数。"""


@dataclass(frozen=True)
class SapaDetail:
    """詳細ページから抽出したSA/PA1件分の情報。"""

    name: str
    """方向表記を除去した施設名。"""

    road_name: str | None
    """路線名。"""

    direction: Direction | None
    """正規化済み上り/下り区分。上下集約施設は``None``。"""

    area_direction: str | None
    """方面(例: 青森方面)。"""

    address: str | None
    """住所。"""

    postal_code: str | None
    """郵便番号。"""

    tel: str | None
    """電話番号。"""

    opening_hours: str | None
    """営業時間。"""

    parking: Parking | None
    """駐車場台数の内訳。"""

    websites: tuple[str, ...]
    """施設ホームページURL列。"""

    facilities: tuple[str, ...]
    """施設設備・サービスのタグ列。"""

    coordinate: Coordinate | None
    """サイトが直接提供する座標(4.1)。現3サイトは通常``None``。"""


class SapaSite(Protocol):
    """SA/PAサイトアダプタが満たすべき共通契約。

    HTTP取得は行わない(純粋なURL構成とパースのみ。取得は``sapa.collector``が
    ``PageFetcher``で行う)。
    """

    key: str
    """サイト識別子("east" | "central" | "west")。レジューム・ログ・サイト
    帰属の識別子として用いる。"""

    def owns_url(self, url: str) -> bool:
        """``url`` が当該サイトの詳細ページに帰属するかを判定する(サイト失敗隔離用)。"""
        ...

    def listing_urls(self, prefectures: Sequence[Prefecture]) -> tuple[str, ...]:
        """対象都道府県列から関連する一覧URL群を構成する。"""
        ...

    def parse_listing(self, page: HtmlPage) -> SapaListingResult:
        """一覧ページをパースし、スタブ列と存在確認できたURL集合を返す。"""
        ...

    def extract_detail(self, page: HtmlPage, detail_url: str) -> SapaDetail:
        """詳細ページをパースし、``SapaDetail`` を抽出する。"""
        ...


# east/central/west の3アダプタが揃うタスク3.4で登録順(east, central, west)に
# 差し替える。本タスク時点ではアダプタが未実装のため空タプル。
ALL_SITES: tuple[SapaSite, ...] = ()
