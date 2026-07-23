"""サイトアダプタ共通契約(sapa.sites)の検証(タスク2.3)。

design.md「sapa.sites(SapaSiteプロトコルと3アダプタ)」節の型定義(``SapaStub``・
``SapaListingResult``・``SapaDetail``・``SapaSite``プロトコル・``ALL_SITES``)と、
research.md「上下線・名称正規化の方針」の共通ヘルパ(上下線の正規化・名称からの
方向表記除去)を検証する。上り/下り区分の正規化と方向表記除去はNEXCO東日本
(「Pasar蓮田(上り線)・東北自動車道」)・NEXCO中日本(「港北PA（上り）」)の実測
表記(research.md参照)を基準に、半角/全角括弧の両方を扱う。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from roadstop_scraper.geojson import Coordinate, Direction, Parking, Prefecture
from roadstop_scraper.sapa.sites import (
    ALL_SITES,
    SapaDetail,
    SapaListingResult,
    SapaSite,
    SapaStub,
    normalize_direction,
    strip_direction_notation,
)
from roadstop_scraper.scraping.parser import HtmlPage


class Test上下線表記の正規化:
    @pytest.mark.parametrize(
        "raw",
        ["(上)", "(上り)", "上り方面", "上り線", "（上り）", "（上）", "（上り線）", "（上り方面）"],
    )
    def test_上下線表記の正規化の検証_上り方向の表記だった場合_Direction上りへ正規化される(self, raw: str) -> None:
        assert normalize_direction(raw) is Direction.UP

    @pytest.mark.parametrize(
        "raw",
        ["(下)", "(下り)", "下り方面", "下り線", "（下り）", "（下）", "（下り線）", "（下り方面）"],
    )
    def test_上下線表記の正規化の検証_下り方向の表記だった場合_Direction下りへ正規化される(self, raw: str) -> None:
        assert normalize_direction(raw) is Direction.DOWN

    @pytest.mark.parametrize("raw", ["蓮田SA", "", "上尾SA", "港北PA"])
    def test_上下線表記の正規化の検証_方向表記を含まない場合_Noneが返る(self, raw: str) -> None:
        assert normalize_direction(raw) is None


class Test施設名からの方向表記除去:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Pasar蓮田(上り線)", "Pasar蓮田"),
            ("蓮田SA(上)", "蓮田SA"),
            ("蓮田SA(上り)", "蓮田SA"),
            ("蓮田SA上り方面", "蓮田SA"),
            ("港北PA（上り）", "港北PA"),
            ("港北PA（下り）", "港北PA"),
            ("蓮田SA(下)", "蓮田SA"),
            ("蓮田SA(下り)", "蓮田SA"),
            ("蓮田SA下り方面", "蓮田SA"),
            ("蓮田SA下り線", "蓮田SA"),
        ],
    )
    def test_施設名からの方向表記除去の検証_方向表記を含む名称だった場合_表記が除去され余分な空白や括弧が残らない(
        self, raw: str, expected: str
    ) -> None:
        result = strip_direction_notation(raw)

        assert result == expected
        assert "(" not in result
        assert ")" not in result
        assert "（" not in result
        assert "）" not in result

    def test_施設名からの方向表記除去の検証_方向表記を含まない名称だった場合_そのまま返る(self) -> None:
        assert strip_direction_notation("上尾サービスエリア") == "上尾サービスエリア"


_EAST_URL = "https://www.driveplaza.com/sapa/1040/1040021/1/"
_CENTRAL_URL = "https://sapa.c-nexco.co.jp/sapa?sapainfoid=17"
_WEST_URL = "https://www.w-holdings.co.jp/sapa/30020/"


class Test全サイト登録:
    def test_全サイト登録の検証_3アダプタ登録後だった場合_東中西の順で3件登録される(self) -> None:
        assert len(ALL_SITES) == 3
        assert tuple(site.key for site in ALL_SITES) == ("east", "central", "west")

    def test_全サイト登録の検証_ALL_SITESの各サイトだった場合_listing_kindがhtml_html_jsonの順である(self) -> None:
        assert tuple(site.listing_kind for site in ALL_SITES) == ("html", "html", "json")

    @pytest.mark.parametrize(
        ("key", "own_url", "other_urls"),
        [
            ("east", _EAST_URL, (_CENTRAL_URL, _WEST_URL)),
            ("central", _CENTRAL_URL, (_EAST_URL, _WEST_URL)),
            ("west", _WEST_URL, (_EAST_URL, _CENTRAL_URL)),
        ],
    )
    def test_全サイト登録の検証_各サイトのowns_urlだった場合_自サイトのURLにのみ真を返す(
        self, key: str, own_url: str, other_urls: tuple[str, ...]
    ) -> None:
        site = next(s for s in ALL_SITES if s.key == key)

        assert site.owns_url(own_url) is True
        for other_url in other_urls:
            assert site.owns_url(other_url) is False


class _FakeSapaSite:
    """``SapaSite``プロトコルを満たす最小の偽アダプタ(構造的な適合性の検証用)。"""

    key = "fake"

    def owns_url(self, url: str) -> bool:
        return "fake-sapa.example" in url

    def listing_urls(self, prefectures: Sequence[Prefecture]) -> tuple[str, ...]:
        return tuple(f"https://fake-sapa.example/list/{p.code}" for p in prefectures)

    def parse_listing(self, page: HtmlPage) -> SapaListingResult:
        stub = SapaStub(display_name="蓮田SA(上り線)", detail_url="https://fake-sapa.example/detail/1")
        return SapaListingResult(stubs=(stub,), listed_urls=frozenset({stub.detail_url}), skipped_count=0)

    def extract_detail(self, page: HtmlPage, detail_url: str) -> SapaDetail:
        return SapaDetail(
            name="蓮田SA",
            road_name="東北自動車道",
            direction=Direction.UP,
            area_direction="青森方面",
            address="埼玉県蓮田市大字川島370番地",
            postal_code="349-0112",
            tel="0480-xx-xxxx",
            opening_hours="24時間",
            parking=Parking(large=10, standard=100, disabled=2),
            websites=("https://fake-sapa.example/pr/1",),
            facilities=("レストラン", "コンビニ"),
            coordinate=Coordinate(longitude=139.7, latitude=35.9),
        )


class TestSapaSiteプロトコル:
    def test_SapaSiteプロトコルの検証_最小の偽アダプタだった場合_プロトコルの各操作が利用できる(self) -> None:
        site: SapaSite = _FakeSapaSite()

        assert site.key == "fake"
        assert site.owns_url("https://fake-sapa.example/detail/1") is True
        assert site.owns_url("https://other.example/detail/1") is False

        prefecture = Prefecture("11", "saitama", "埼玉県")
        urls = site.listing_urls((prefecture,))
        assert urls == ("https://fake-sapa.example/list/11",)

        listing = site.parse_listing(page=None)  # type: ignore[arg-type]
        assert listing.skipped_count == 0
        assert len(listing.stubs) == 1
        assert listing.listed_urls == frozenset({listing.stubs[0].detail_url})

        detail = site.extract_detail(page=None, detail_url=listing.stubs[0].detail_url)  # type: ignore[arg-type]
        assert detail.name == "蓮田SA"
        assert detail.direction is Direction.UP

    def test_SapaSiteプロトコルの検証_SapaDetailはfrozenデータクラスだった場合_replaceで複製できる(self) -> None:
        detail = _FakeSapaSite().extract_detail(page=None, detail_url="dummy")  # type: ignore[arg-type]

        down_detail = replace(detail, direction=Direction.DOWN)

        assert down_detail.direction is Direction.DOWN
        assert detail.direction is Direction.UP
