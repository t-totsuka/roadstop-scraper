"""一覧/検索ページからの道の駅名称・詳細URL・座標の収集(listing)。

対象都道府県の一覧ページを1回だけ取得し、``div.js-data-box``要素群から
``data-name``/``data-link``/``data-lat``/``data-lng``を相関抽出する。
座標(``data-lat``/``data-lng``)のみが解釈できない要素は、その1件だけを
``StationStub``化せずスキップし、他の要素の処理は継続する
(research.md「一覧/検索ページの構造実測とページネーション調査」参照)。
"""

from __future__ import annotations

from dataclasses import dataclass

from roadstop_scraper.common.logging_setup import get_logger
from roadstop_scraper.geojson import Coordinate, Prefecture
from roadstop_scraper.michinoeki.site_urls import build_search_url
from roadstop_scraper.scraping import PageFetcher, ScrapingEngineError, parse_html

__all__ = [
    "ListingResult",
    "ListingUnavailableError",
    "StationStub",
    "fetch_station_stubs",
]

_logger = get_logger(__name__)

_LISTING_SELECTOR = "div.js-data-box"


@dataclass(frozen=True)
class StationStub:
    """一覧ページから抽出した道の駅1件分の中間表現。"""

    name: str
    """道の駅名称。"""

    detail_url: str
    """詳細ページの絶対/相対URL(``data-link``の値)。"""

    coordinate: Coordinate
    """WGS84座標(``data-lat``/``data-lng``から構築)。"""


@dataclass(frozen=True)
class ListingResult:
    """一覧ページ1回分の取得・抽出結果。"""

    stubs: tuple[StationStub, ...]
    """名称・詳細URL・座標がすべて解釈できた要素のみ。"""

    listed_urls: frozenset[str]
    """``data-name``/``data-link``が解釈できた全要素の``data-link``集合。

    座標欠落で``stubs``化できなかった要素の``data-link``も含む(8.1〜8.2、
    「一覧に実在した」という事実を呼び出し側の削除判定から除外するため)。
    """

    skipped_count: int
    """座標欠落・数値変換不能によりスキップされた要素数。"""


class ListingUnavailableError(ScrapingEngineError):
    """一覧ページから``js-data-box``要素が1件も取得できなかった場合に送出される。"""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"URL '{url}' の一覧ページから道の駅の要素を1件も取得できませんでした")


def fetch_station_stubs(fetcher: PageFetcher, prefecture: Prefecture) -> ListingResult:
    """都道府県の一覧ページを取得し、道の駅ごとのListingResultを返す。

    ページネーションは辿らない(1ページ目に該当都道府県の全件が
    ``js-data-box``として埋め込まれているため。research.md参照)。
    """
    url = build_search_url(prefecture)
    fetched = fetcher.fetch_text(url)
    page = parse_html(fetched.text, fetched.url)

    names = page.find_attrs(_LISTING_SELECTOR, "data-name")
    links = page.find_attrs(_LISTING_SELECTOR, "data-link")
    lats = page.find_attrs(_LISTING_SELECTOR, "data-lat")
    lngs = page.find_attrs(_LISTING_SELECTOR, "data-lng")

    if not names:
        raise ListingUnavailableError(fetched.url)

    stubs: list[StationStub] = []
    listed_urls: set[str] = set()
    skipped_count = 0

    # find_attrsは同一セレクタへの4回の呼び出しであり、同一DOM順序・同一件数の
    # リストを返す前提のため、インデックスで4属性を相関させる
    # (research.md「Design Decisions」参照)。
    for name, link, lat, lng in zip(names, links, lats, lngs, strict=True):
        if name is None or link is None:
            # 実運用では発生しない想定の防御的経路。座標欠落とは別カテゴリのため
            # listed_urls・skipped_countのいずれにも計上しない。
            continue

        coordinate = _parse_coordinate(lat, lng)
        if coordinate is None:
            skipped_count += 1
            _logger.warning(
                "座標を解釈できないため道の駅をスキップ: url=%s prefecture=%s data-lat=%r data-lng=%r",
                link,
                prefecture.name_ja,
                lat,
                lng,
            )
            listed_urls.add(link)
            continue

        listed_urls.add(link)
        stubs.append(StationStub(name=name, detail_url=link, coordinate=coordinate))

    return ListingResult(
        stubs=tuple(stubs),
        listed_urls=frozenset(listed_urls),
        skipped_count=skipped_count,
    )


def _parse_coordinate(lat: str | None, lng: str | None) -> Coordinate | None:
    """``data-lat``/``data-lng``をCoordinateへ変換する。いずれか欠落・数値変換不能ならNone。"""
    latitude = _parse_float(lat)
    longitude = _parse_float(lng)
    if latitude is None or longitude is None:
        return None
    return Coordinate(longitude=longitude, latitude=latitude)


def _parse_float(value: str | None) -> float | None:
    """文字列をfloatへ変換する。Noneまたは数値変換不能な場合はNoneを返す。"""
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
