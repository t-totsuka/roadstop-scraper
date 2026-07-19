"""国土地理院AddressSearch APIによる住所→座標の補完。

座標を直接掲載しない施設向けに、住所から座標を補完する``GsiGeocoder``を
提供するモジュール(design.md「sapa.geocoding」節参照)。

``GsiGeocoder.geocode``は例外を一切送出しない契約(design.mdのInvariant)で、
候補なし・応答構造不正・非有限座標・取得失敗(``ScrapingEngineError``)の
いずれも欠損値(``None``)として扱い、WARNINGログを記録する。補完に成功した
場合は住所・座標をINFOログへ記録する(4.4)。
"""

from __future__ import annotations

import math
from urllib.parse import quote

from roadstop_scraper.common.logging_setup import get_logger
from roadstop_scraper.geojson.models import Coordinate
from roadstop_scraper.scraping.errors import ScrapingEngineError
from roadstop_scraper.scraping.fetcher import PageFetcher

__all__ = ["GsiGeocoder"]

_ADDRESS_SEARCH_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch?q={query}"

_logger = get_logger(__name__)


class GsiGeocoder:
    """国土地理院 AddressSearch APIで住所を座標化する。"""

    def __init__(self, fetcher: PageFetcher) -> None:
        # 補完専用のフェッチャー(呼び出し側が別インスタンスを注入することで、
        # サイト取得用のRateLimiterと独立した最小間隔・リトライが適用される。8.1)
        self._fetcher = fetcher

    def geocode(self, address: str) -> Coordinate | None:
        """住所を座標化する。

        候補なし・応答形式不正・非有限座標・取得失敗(``ScrapingEngineError``)は
        いずれもWARNINGログを記録した上で``None``を返し、例外は送出しない。
        """
        url = _ADDRESS_SEARCH_URL.format(query=quote(address))

        try:
            response = self._fetcher.fetch_json(url)
        except ScrapingEngineError as exc:
            _logger.warning("ジオコーディング取得失敗: address=%s error=%s", address, exc)
            return None

        coordinate = _extract_first_coordinate(response)
        if coordinate is None:
            _logger.warning("ジオコーディング候補なしまたは応答不正: address=%s", address)
            return None

        _logger.info(
            "ジオコーディング成功: address=%s longitude=%s latitude=%s",
            address,
            coordinate.longitude,
            coordinate.latitude,
        )
        return coordinate


def _extract_first_coordinate(response: object) -> Coordinate | None:
    """GSI応答(``object``型)から第1候補の座標を防御的に抽出する。

    構造不一致(トップレベルがリストでない・要素が辞書でない・
    ``geometry.coordinates``の欠落や型不一致)・非有限値はすべて``None``扱いと
    する(design.md Postconditions)。
    """
    if not isinstance(response, list) or len(response) == 0:
        return None

    first_candidate = response[0]
    if not isinstance(first_candidate, dict):
        return None

    geometry = first_candidate.get("geometry")
    if not isinstance(geometry, dict):
        return None

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
        return None

    longitude, latitude = coordinates
    if not _is_finite_number(longitude) or not _is_finite_number(latitude):
        return None

    return Coordinate(longitude=float(longitude), latitude=float(latitude))


def _is_finite_number(value: object) -> bool:
    """``bool``を除く``int``/``float``かつ有限値かどうかを判定する。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)
