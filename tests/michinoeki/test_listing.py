"""一覧ページからの道の駅名称・詳細URL・座標の収集(listing)の検証。

タスク3.1の観測可能な完了条件を検証する: フィクスチャHTMLから名称・詳細URL・
座標が正しく対応付けて抽出できること、要素0件で取得失敗となること、一部要素の
座標欠落時にその1件のみがスキップされスキップ件数と存在確認済みURLの集合に
反映されること。偽セッション(``_FakeResponse``/``_FakeSession``/
``_FakeRateLimiter``)は``tests/scraping/test_integration_fetch_to_extract.py``と
同じパターンを用い、実際の``PageFetcher``へ注入する(追加のモックライブラリは
導入しない)。
"""

from __future__ import annotations

import pytest

from roadstop_scraper.geojson import Coordinate, find_prefecture
from roadstop_scraper.michinoeki.listing import (
    ListingResult,
    ListingUnavailableError,
    StationStub,
    fetch_station_stubs,
)
from roadstop_scraper.michinoeki.site_urls import build_search_url
from roadstop_scraper.scraping.config import ScrapingConfig
from roadstop_scraper.scraping.fetcher import PageFetcher

# 実際の一覧/検索ページのjs-data-box構造を模したフィクスチャHTML
# (research.md「一覧/検索ページの構造実測とページネーション調査」参照)。
_FIXTURE_HTML_ALL_VALID = """
<html>
  <body>
    <main>
      <div class="js-data-box" data-name="道の駅 三笠" data-link="/stations/views/18786" data-lat="43.123" data-lng="141.900"></div>
      <div class="js-data-box" data-name="道の駅 スタープラザ芦別" data-link="/stations/views/18787" data-lat="43.456" data-lng="142.400"></div>
    </main>
  </body>
</html>
"""

_FIXTURE_HTML_NO_ELEMENTS = """
<html>
  <body>
    <main>
      <p>該当する道の駅はありません</p>
    </main>
  </body>
</html>
"""

# 3件のうち2件目のみ座標(data-lat/data-lng)が欠落しているフィクスチャ
_FIXTURE_HTML_ONE_COORDINATE_MISSING = """
<html>
  <body>
    <main>
      <div class="js-data-box" data-name="道の駅 三笠" data-link="/stations/views/18786" data-lat="43.123" data-lng="141.900"></div>
      <div class="js-data-box" data-name="道の駅 座標欠落" data-link="/stations/views/99999" data-lat="" data-lng=""></div>
      <div class="js-data-box" data-name="道の駅 許田" data-link="/stations/views/19813" data-lat="26.654" data-lng="128.038"></div>
    </main>
  </body>
</html>
"""


class _FakeResponse:
    """``ResponseLike``を満たす偽レスポンス。"""

    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.apparent_encoding = "utf-8"


class _FakeSession:
    """HTTP層のみをスタブ化する偽セッション。事前登録した応答を返す。"""

    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[str] = []

    def get(self, url, *, timeout, headers):
        self.calls.append(url)
        return self._response


class _FakeRateLimiter:
    """試験を高速化するため、待機せず呼び出し回数のみ記録する偽RateLimiter。"""

    def __init__(self) -> None:
        self.wait_count = 0

    def wait(self) -> None:
        self.wait_count += 1


def _fast_config() -> ScrapingConfig:
    return ScrapingConfig(
        timeout_seconds=5.0,
        max_retries=0,
        retry_wait_seconds=0.0,
        min_request_interval_seconds=0.0,
    )


def _build_fetcher(html: str) -> tuple[PageFetcher, _FakeSession]:
    response = _FakeResponse(
        200,
        html.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    session = _FakeSession(response)
    fetcher = PageFetcher(_fast_config(), rate_limiter=_FakeRateLimiter(), session=session)
    return fetcher, session


def test_一覧抽出の検証_全要素の座標が解釈できる場合_名称_詳細URL_座標が正しく対応付けて抽出できる():
    prefecture = find_prefecture("01")
    fetcher, session = _build_fetcher(_FIXTURE_HTML_ALL_VALID)

    result = fetch_station_stubs(fetcher, prefecture)

    assert isinstance(result, ListingResult)
    assert result.stubs == (
        StationStub(
            name="道の駅 三笠",
            detail_url="/stations/views/18786",
            coordinate=Coordinate(longitude=141.900, latitude=43.123),
        ),
        StationStub(
            name="道の駅 スタープラザ芦別",
            detail_url="/stations/views/18787",
            coordinate=Coordinate(longitude=142.400, latitude=43.456),
        ),
    )
    assert result.listed_urls == frozenset({"/stations/views/18786", "/stations/views/18787"})
    assert result.skipped_count == 0

    # ページネーションを辿らず、一覧ページの取得は1回のみであること
    assert session.calls == [build_search_url(prefecture)]


def test_一覧抽出の検証_js_data_box要素が0件の場合_ListingUnavailableErrorが送出される():
    prefecture = find_prefecture("01")
    fetcher, session = _build_fetcher(_FIXTURE_HTML_NO_ELEMENTS)

    with pytest.raises(ListingUnavailableError):
        fetch_station_stubs(fetcher, prefecture)

    # 取得失敗と判定するまでにfetch_textは1回だけ呼ばれていること
    assert session.calls == [build_search_url(prefecture)]


def test_一覧抽出の検証_一部要素のみ座標が欠落する場合_その1件のみがスキップされ他は抽出される():
    prefecture = find_prefecture("47")
    fetcher, session = _build_fetcher(_FIXTURE_HTML_ONE_COORDINATE_MISSING)

    result = fetch_station_stubs(fetcher, prefecture)

    # 座標が正常な2件のみがstubsに含まれる(座標欠落の1件は除外される)
    assert result.stubs == (
        StationStub(
            name="道の駅 三笠",
            detail_url="/stations/views/18786",
            coordinate=Coordinate(longitude=141.900, latitude=43.123),
        ),
        StationStub(
            name="道の駅 許田",
            detail_url="/stations/views/19813",
            coordinate=Coordinate(longitude=128.038, latitude=26.654),
        ),
    )
    # スキップ件数は座標欠落の1件のみ
    assert result.skipped_count == 1
    # 座標欠落でstubs化できなかった要素のdetail_urlも、一覧には実在したためlisted_urlsに含まれる
    assert result.listed_urls == frozenset(
        {
            "/stations/views/18786",
            "/stations/views/99999",
            "/stations/views/19813",
        }
    )

    assert session.calls == [build_search_url(prefecture)]


def test_一覧抽出の検証_取得URLの検証_build_search_urlの結果と一致する():
    prefecture = find_prefecture("13")
    fetcher, session = _build_fetcher(_FIXTURE_HTML_ALL_VALID)

    fetch_station_stubs(fetcher, prefecture)

    assert session.calls == [build_search_url(prefecture)]


# 要素は存在するが全要素のdata-linkが解釈できないフィクスチャ(属性リネーム等の
# 構造変化を模す)。
_FIXTURE_HTML_ALL_LINKS_MISSING = """
<html>
  <body>
    <main>
      <div class="js-data-box" data-name="道の駅 三笠" data-lat="43.123" data-lng="141.900"></div>
      <div class="js-data-box" data-name="道の駅 許田" data-lat="26.654" data-lng="128.038"></div>
    </main>
  </body>
</html>
"""

# 2件目のみdata-nameが欠落しているフィクスチャ
_FIXTURE_HTML_ONE_NAME_MISSING = """
<html>
  <body>
    <main>
      <div class="js-data-box" data-name="道の駅 三笠" data-link="/stations/views/18786" data-lat="43.123" data-lng="141.900"></div>
      <div class="js-data-box" data-link="/stations/views/88888" data-lat="43.456" data-lng="142.400"></div>
    </main>
  </body>
</html>
"""

# 2件目のみdata-latが非有限値("nan")のフィクスチャ
_FIXTURE_HTML_ONE_NAN_COORDINATE = """
<html>
  <body>
    <main>
      <div class="js-data-box" data-name="道の駅 三笠" data-link="/stations/views/18786" data-lat="43.123" data-lng="141.900"></div>
      <div class="js-data-box" data-name="道の駅 非有限" data-link="/stations/views/77777" data-lat="nan" data-lng="142.400"></div>
    </main>
  </body>
</html>
"""


def test_一覧抽出の検証_要素は存在するが全要素のdata_linkが解釈できない場合_ListingUnavailableErrorが送出される():
    """属性レベルの構造変化(data-linkリネーム等)を「全駅が一覧から消失した」と
    誤認すると前回出力の全駅が削除状態へ一斉遷移するため、URLを1件も確認でき
    ない一覧は取得失敗として中断されることを検証する(レビュー指摘の回帰テスト)。
    """
    prefecture = find_prefecture("01")
    fetcher, session = _build_fetcher(_FIXTURE_HTML_ALL_LINKS_MISSING)

    with pytest.raises(ListingUnavailableError):
        fetch_station_stubs(fetcher, prefecture)

    assert session.calls == [build_search_url(prefecture)]


def test_一覧抽出の検証_一部要素のみ名称が欠落する場合_その1件はスキップされるがlisted_urlsには含まれる():
    """data-nameのみ欠落した要素はstub化できずスキップされるが、data-linkが
    取れている以上「一覧に実在した」事実をlisted_urlsへ残し、merge側で前回出力が
    誤って削除状態へ遷移しないことを検証する(レビュー指摘の回帰テスト)。
    """
    prefecture = find_prefecture("01")
    fetcher, _session = _build_fetcher(_FIXTURE_HTML_ONE_NAME_MISSING)

    result = fetch_station_stubs(fetcher, prefecture)

    assert [stub.name for stub in result.stubs] == ["道の駅 三笠"]
    assert result.skipped_count == 1
    # 名称欠落の要素のdata-linkもlisted_urlsに含まれる。
    assert result.listed_urls == frozenset({"/stations/views/18786", "/stations/views/88888"})


def test_一覧抽出の検証_座標が非有限値の場合_その1件のみがスキップされ他は抽出される():
    """"nan"等はfloat変換自体は成功するが、座標として通すと出力前検証で都道府県
    全体が中断されるため、一覧段階で当該1件のスキップに収まることを検証する
    (レビュー指摘の回帰テスト)。
    """
    prefecture = find_prefecture("01")
    fetcher, _session = _build_fetcher(_FIXTURE_HTML_ONE_NAN_COORDINATE)

    result = fetch_station_stubs(fetcher, prefecture)

    assert [stub.name for stub in result.stubs] == ["道の駅 三笠"]
    assert result.skipped_count == 1
    assert "/stations/views/77777" in result.listed_urls
