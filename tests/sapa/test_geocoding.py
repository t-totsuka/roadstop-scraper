"""GsiGeocoderのユニットテスト。

``PageFetcher``は``fetch_json(url) -> object``のみを呼び出すため、テストでは
その最小インタフェースを満たす偽フェッチャー(``_FakeFetcher``)を注入する
(``tests/scraping/test_fetcher.py``の``SessionLike``偽装と同様の方針)。
"""

from __future__ import annotations

import logging

import pytest

from roadstop_scraper.geojson.models import Coordinate
from roadstop_scraper.sapa.geocoding import GsiGeocoder
from roadstop_scraper.scraping.errors import FetchFailedError

_LOGGER_NAME = "roadstop_scraper.sapa.geocoding"


class _FakeFetcher:
    """事前に登録した応答(またはraiseすべき例外)を返す偽フェッチャー。"""

    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[str] = []

    def fetch_json(self, url: str) -> object:
        self.calls.append(url)
        if isinstance(self._response, BaseException):
            raise self._response
        return self._response


def test_ジオコーディングの検証_第1候補が正常な応答の場合_座標を返す():
    response = [
        {"geometry": {"coordinates": [139.767125, 35.681236]}, "properties": {"title": "東京駅"}},
        {"geometry": {"coordinates": [999.0, 999.0]}, "properties": {"title": "無視される第2候補"}},
    ]
    fetcher = _FakeFetcher(response)
    geocoder = GsiGeocoder(fetcher)

    result = geocoder.geocode("東京都千代田区丸の内1丁目")

    assert result == Coordinate(longitude=139.767125, latitude=35.681236)


def test_ジオコーディングの検証_URLに住所をURLエンコードして問い合わせる():
    response = [{"geometry": {"coordinates": [139.767125, 35.681236]}}]
    fetcher = _FakeFetcher(response)
    geocoder = GsiGeocoder(fetcher)

    geocoder.geocode("東京都 千代田区")

    assert len(fetcher.calls) == 1
    called_url = fetcher.calls[0]
    assert called_url.startswith("https://msearch.gsi.go.jp/address-search/AddressSearch?q=")
    assert " " not in called_url
    assert "東京都" not in called_url  # 生の日本語文字列がそのまま連結されていない


def test_ジオコーディングの検証_候補が空リストの場合_Noneを返し警告ログを記録する(caplog):
    fetcher = _FakeFetcher([])
    geocoder = GsiGeocoder(fetcher)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = geocoder.geocode("存在しない住所")

    assert result is None
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"not": "a list"}, id="トップレベルがリストでない"),
        pytest.param([{"properties": {"title": "geometryなし"}}], id="geometryキー欠落"),
        pytest.param([{"geometry": {}}], id="coordinatesキー欠落"),
        pytest.param([{"geometry": {"coordinates": [139.0]}}], id="coordinatesが要素数不足"),
        pytest.param([{"geometry": {"coordinates": "不正な型"}}], id="coordinatesがリストでない"),
        pytest.param([{"geometry": None}], id="geometryがNone"),
        pytest.param(["文字列要素"], id="候補要素が辞書でない"),
    ],
)
def test_ジオコーディングの検証_応答構造が不正な場合_例外を送出せずNoneを返す(response):
    fetcher = _FakeFetcher(response)
    geocoder = GsiGeocoder(fetcher)

    result = geocoder.geocode("テスト住所")

    assert result is None


@pytest.mark.parametrize(
    "coordinates",
    [
        pytest.param([float("nan"), 35.681236], id="経度がNaN"),
        pytest.param([139.767125, float("inf")], id="緯度が無限大"),
        pytest.param([float("-inf"), 35.681236], id="経度が負の無限大"),
        pytest.param(["139.767125", 35.681236], id="経度が文字列型"),
        pytest.param([139.767125, None], id="緯度がNone"),
    ],
)
def test_ジオコーディングの検証_座標値が非有限または不正な型の場合_Noneを返す(coordinates):
    response = [{"geometry": {"coordinates": coordinates}}]
    fetcher = _FakeFetcher(response)
    geocoder = GsiGeocoder(fetcher)

    result = geocoder.geocode("テスト住所")

    assert result is None


def test_ジオコーディングの検証_フェッチャーが取得失敗例外を送出する場合_Noneを返し例外を伝播しない(caplog):
    fetcher = _FakeFetcher(FetchFailedError("https://msearch.gsi.go.jp/address-search/AddressSearch?q=x", 503, 3))
    geocoder = GsiGeocoder(fetcher)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = geocoder.geocode("テスト住所")

    assert result is None
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1


def test_ジオコーディングの検証_成功時にINFOログへ住所と座標を記録する(caplog):
    response = [{"geometry": {"coordinates": [139.767125, 35.681236]}}]
    fetcher = _FakeFetcher(response)
    geocoder = GsiGeocoder(fetcher)

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        geocoder.geocode("東京都千代田区丸の内1丁目")

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    message = info_records[0].getMessage()
    assert "東京都千代田区丸の内1丁目" in message
    assert "139.767125" in message
    assert "35.681236" in message
