"""一覧/検索ページからの道の駅名称・詳細URL・座標の収集(listing)。

対象都道府県の一覧ページを1回だけ取得し、``div.js-data-box``要素群から
``data-name``/``data-link``/``data-lat``/``data-lng``を相関抽出する。
座標(``data-lat``/``data-lng``)・名称・詳細URLのいずれかが解釈できない要素は、
その1件だけを``StationStub``化せずスキップし、他の要素の処理は継続する。
詳細URL(``data-link``)を1件も確認できない場合は、属性レベルの構造変化を
「全駅の一覧からの消失」と誤認しないよう``ListingUnavailableError``で
当該都道府県の処理を中断させる
(research.md「一覧/検索ページの構造実測とページネーション調査」参照)。
"""

from __future__ import annotations

import math
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
    """``data-link``が解釈できた全要素の``data-link``集合。

    座標欠落・名称欠落で``stubs``化できなかった要素の``data-link``も含む
    (8.1〜8.2、「一覧に実在した」という事実を呼び出し側の削除判定から
    除外するため)。
    """

    skipped_count: int
    """名称欠落、または座標欠落・数値変換不能・非有限値によりスキップされた要素数。"""


class ListingUnavailableError(ScrapingEngineError):
    """一覧ページから道の駅のURL(``data-link``)を1件も確認できなかった場合に送出される。

    ``js-data-box``要素が0件の場合に加え、要素は存在するが全要素の``data-link``が
    解釈できない場合(属性リネーム等の構造変化)も含む。後者を「一覧から全駅が
    消失した」と誤認すると、前回出力の全駅が削除状態へ一斉遷移してしまうため、
    いずれも一覧取得の失敗として当該都道府県の処理を中断させる。
    """

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"URL '{url}' の一覧ページから道の駅を1件も確認できませんでした")


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

    stubs: list[StationStub] = []
    listed_urls: set[str] = set()
    skipped_count = 0

    # find_attrsは同一セレクタへの4回の呼び出しであり、同一DOM順序・同一件数の
    # リストを返す前提のため、インデックスで4属性を相関させる
    # (research.md「Design Decisions」参照)。
    for name, link, lat, lng in zip(names, links, lats, lngs, strict=True):
        if link is None or name is None or not link or not name:
            # data-link/data-nameが解釈できない要素はstub化できずスキップする。
            # data-linkが取れている場合は「一覧に実在した」事実をlisted_urlsへ
            # 残し、呼び出し側の削除判定(merge)で前回出力が誤って削除状態へ
            # 遷移しないようにする(8.1〜8.2)。
            skipped_count += 1
            _logger.warning(
                "名称または詳細URLを解釈できないため道の駅をスキップ: prefecture=%s data-name=%r data-link=%r",
                prefecture.name_ja,
                name,
                link,
            )
            if link:
                listed_urls.add(link)
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

    if not listed_urls:
        # js-data-box要素が0件、または全要素のdata-linkが解釈できない場合。
        # 空のlisted_urlsを正常結果として返すと、merge側で前回出力の全駅が
        # 「一覧から消失した」と誤判定され一斉に削除状態へ遷移するため、
        # 一覧取得の失敗として当該都道府県の処理を中断させる。
        raise ListingUnavailableError(fetched.url)

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
    """文字列をfloatへ変換する。Noneまたは数値変換不能・非有限値の場合はNoneを返す。

    ``"nan"``/``"inf"``等はfloat変換自体は成功するが、座標として通すと出力前検証
    (``math.isfinite``チェック)で都道府県全体が中断されてしまうため、ここで
    弾いて当該1件のスキップに収める。
    """
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number
