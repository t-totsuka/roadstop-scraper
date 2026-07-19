"""``sapa.collector.SapaPartialStore``(タスク4.1)の検証。

design.md「sapa.collector」State Managementのとおり、実行横断(サイト横断・
都道府県横断)の単一キー``"sapa-partial"``で部分結果(features・
skipped_counts・geocoded_counts)を``common.ResumeStore``へ逐次永続化する
クラスの振る舞いを検証する。05の``_PartialResultStore``(都道府県単位・
フラットなskipped_count)とは異なり、都道府県コード別(および都道府県不明の
"unknown"バケット)のカウントマップを保持する点が本タスクの主眼(5.3, 7.2)。

観測可能な完了条件:
- 追記→復元の往復で内容が一致すること(features/skipped_counts/geocoded_counts)
- 同一``source_url``の再追記が重複しないこと(冪等)
- ``clear()``後は同一インスタンス・新規インスタンスとも空から始まること
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import pytest

from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import (
    PREFECTURES,
    Coordinate,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
)
from roadstop_scraper.sapa.collector import SapaPartialStore, SiteCollectResult, SiteListingError, collect_site
from roadstop_scraper.sapa.sites import SapaDetail, SapaListingResult, SapaStub
from roadstop_scraper.scraping import FetchedContent, FetchFailedError, StructureChangedError, UrlResumeTracker

_COLLECTOR_LOGGER_NAME = "roadstop_scraper.sapa.collector"

_TOKYO = next(p for p in PREFECTURES if p.code == "13")


@dataclass
class _FakeGeocoder:
    """呼び出しを記録し、事前登録した座標(またはNone)を返す偽ジオコーダー。

    ``collect_site``は``geocoder.geocode(address)``のみを呼び出すため、
    ``GsiGeocoder``を継承する必要はない(``tests/sapa/test_geocoding.py``の
    ``_FakeFetcher``と同様、必要最小インタフェースのみを満たす偽物)。
    """

    result: Coordinate | None = None
    calls: list[str] = field(default_factory=list)

    def geocode(self, address: str) -> Coordinate | None:
        self.calls.append(address)
        return self.result


@dataclass
class _FakeFetcher:
    """事前登録した応答(またはraiseすべき例外)をURLごとに返す偽フェッチャー。

    ``collect_site``は``fetch_text``(詳細ページ、および一覧が
    ``listing_kind == "html"``の場合)と``fetch_json``(一覧が
    ``listing_kind == "json"``の場合)のみを呼び出すため、その最小インタ
    フェースのみを満たす(``tests/scraping/test_fetcher.py``の``SessionLike``
    偽装と同様の方針)。
    """

    text_by_url: dict[str, str] = field(default_factory=dict)
    json_by_url: dict[str, object] = field(default_factory=dict)
    raise_by_url: dict[str, Exception] = field(default_factory=dict)
    text_calls: list[str] = field(default_factory=list)
    json_calls: list[str] = field(default_factory=list)

    def fetch_text(self, url: str) -> FetchedContent:
        self.text_calls.append(url)
        if url in self.raise_by_url:
            raise self.raise_by_url[url]
        return FetchedContent(url=url, text=self.text_by_url.get(url, "<html></html>"), encoding="utf-8")

    def fetch_json(self, url: str) -> object:
        self.json_calls.append(url)
        if url in self.raise_by_url:
            raise self.raise_by_url[url]
        return self.json_by_url.get(url)


@dataclass
class _FakeSite:
    """``SapaSite``プロトコルを満たす偽サイトアダプタ(実HTML解析は行わない)。

    ``listing_kind == "json"``の場合、``parse_listing``へ渡される``content``は
    ``_FakeFetcher.fetch_json``が返した値そのもの。本テストでは``json_by_url``へ
    ``SapaListingResult``を直接登録し、``parse_listing``はそれをそのまま返す
    (「一覧の生JSON値」を実際にパースする代わりに、パース済みの結果を偽装する)。

    ``listing_kind == "html"``の場合、``content``は実際に(空の)HTMLを
    パースした``HtmlPage``になる。``HtmlPage.url``が取得元の一覧URLと一致する
    ことを利用し、``listing_by_url``で一覧URLごとの結果を引く。

    ``extract_detail``は``details_by_url``に登録した``SapaDetail``をそのまま
    返すか、``Exception``が登録されていればそれを送出する。
    """

    key: str = "fake"
    listing_kind: Literal["html", "json"] = "json"
    listing_url_list: tuple[str, ...] = ()
    listing_by_url: dict[str, SapaListingResult] = field(default_factory=dict)
    details_by_url: dict[str, SapaDetail | Exception] = field(default_factory=dict)
    detail_calls: list[str] = field(default_factory=list)

    def owns_url(self, url: str) -> bool:
        return True

    def listing_urls(self, prefectures: object) -> tuple[str, ...]:
        return self.listing_url_list

    def parse_listing(self, content: object) -> SapaListingResult:
        if self.listing_kind == "json":
            assert isinstance(content, SapaListingResult)
            return content
        return self.listing_by_url[content.url]  # type: ignore[attr-defined]

    def extract_detail(self, page: object, detail_url: str) -> SapaDetail:
        self.detail_calls.append(detail_url)
        result = self.details_by_url[detail_url]
        if isinstance(result, Exception):
            raise result
        return result


def _make_resume(tmp_path, key: str = "test-sapa") -> UrlResumeTracker:
    return UrlResumeTracker(key, store=ResumeStore(state_dir=tmp_path / ".resume"))


def _make_partial_store(tmp_path) -> SapaPartialStore:
    return SapaPartialStore(store=ResumeStore(state_dir=tmp_path / ".resume"))


def _detail(
    *,
    name: str = "テストSA",
    road_name: str | None = "テスト自動車道",
    address: str | None = "東京都新宿区西新宿1-1",
    coordinate: Coordinate | None = None,
) -> SapaDetail:
    return SapaDetail(
        name=name,
        road_name=road_name,
        direction=None,
        area_direction=None,
        address=address,
        postal_code=None,
        tel="03-1234-5678",
        opening_hours="24時間",
        parking=None,
        websites=(),
        facilities=("売店",),
        coordinate=coordinate,
    )


def _feature(source_url: str, *, name: str = "テストSA", pref_code: str = "13") -> FacilityFeature:
    return FacilityFeature(
        coordinate=Coordinate(longitude=139.7, latitude=35.6),
        properties=FacilityProperties(
            name=name,
            kind=FacilityKind.SAPA,
            pref_code=pref_code,
            pref_name="東京都",
            source_url=source_url,
        ),
    )


def _make_store(tmp_path) -> ResumeStore:
    return ResumeStore(state_dir=tmp_path / ".resume")


def test_add_featureの検証_複数の異なるsource_urlを追加した場合_featuresへ全件反映される(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    partial_store.add_feature(_feature("https://example.com/a"))
    partial_store.add_feature(_feature("https://example.com/b"))

    urls = {f.properties.source_url for f in partial_store.features}
    assert urls == {"https://example.com/a", "https://example.com/b"}
    assert len(partial_store.features) == 2


def test_add_featureの検証_同一source_urlを再追加した場合_件数が増えず新しい内容へ置き換わる(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    partial_store.add_feature(_feature("https://example.com/a", name="旧名称"))
    partial_store.add_feature(_feature("https://example.com/a", name="新名称"))

    assert len(partial_store.features) == 1
    assert partial_store.features[0].properties.name == "新名称"


def test_add_skipの検証_複数の都道府県コードとnoneを追加した場合_コード別とunknownバケットへ集計される(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    partial_store.add_skip("13")
    partial_store.add_skip("13")
    partial_store.add_skip("01")
    partial_store.add_skip(None)

    assert partial_store.skipped_counts == {"13": 2, "01": 1, "unknown": 1}


def test_add_geocodedの検証_複数の都道府県コードを追加した場合_コード別に加算される(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    partial_store.add_geocoded("13")
    partial_store.add_geocoded("13")
    partial_store.add_geocoded("27")

    assert partial_store.geocoded_counts == {"13": 2, "27": 1}


def test_復元の検証_追記後に同じストアから新規構築した場合_features_skipped_counts_geocoded_countsが一致する(
    tmp_path,
):
    store = _make_store(tmp_path)
    partial_store = SapaPartialStore(store=store)

    partial_store.add_feature(_feature("https://example.com/a"))
    partial_store.add_feature(_feature("https://example.com/b"))
    partial_store.add_skip("13")
    partial_store.add_skip(None)
    partial_store.add_geocoded("13")

    restored = SapaPartialStore(store=store)

    assert {f.properties.source_url for f in restored.features} == {
        "https://example.com/a",
        "https://example.com/b",
    }
    assert restored.skipped_counts == {"13": 1, "unknown": 1}
    assert restored.geocoded_counts == {"13": 1}


def test_clearの検証_クリア後は同一インスタンスも新規構築したインスタンスも空から始まる(tmp_path):
    store = _make_store(tmp_path)
    partial_store = SapaPartialStore(store=store)

    partial_store.add_feature(_feature("https://example.com/a"))
    partial_store.add_skip("13")
    partial_store.add_geocoded("13")

    partial_store.clear()

    assert partial_store.features == []
    assert partial_store.skipped_counts == {}
    assert partial_store.geocoded_counts == {}

    restored = SapaPartialStore(store=store)
    assert restored.features == []
    assert restored.skipped_counts == {}
    assert restored.geocoded_counts == {}


def test_初期状態の検証_未保存のストアから構築した場合_空のfeatures_skipped_counts_geocoded_countsで開始する(
    tmp_path,
):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    assert partial_store.features == []
    assert partial_store.skipped_counts == {}
    assert partial_store.geocoded_counts == {}


def test_featuresプロパティの検証_返された一覧を変更した場合_内部状態は影響を受けない(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))
    partial_store.add_feature(_feature("https://example.com/a"))

    returned = partial_store.features
    returned.append(_feature("https://example.com/b"))
    returned.clear()

    assert len(partial_store.features) == 1
    assert partial_store.features[0].properties.source_url == "https://example.com/a"


def test_skipped_countsプロパティの検証_返された辞書を変更した場合_内部状態は影響を受けない(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))
    partial_store.add_skip("13")

    returned = partial_store.skipped_counts
    returned["13"] = 999
    returned["27"] = 1

    assert partial_store.skipped_counts == {"13": 1}


def test_geocoded_countsプロパティの検証_返された辞書を変更した場合_内部状態は影響を受けない(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))
    partial_store.add_geocoded("13")

    returned = partial_store.geocoded_counts
    returned["13"] = 999
    returned["27"] = 1

    assert partial_store.geocoded_counts == {"13": 1}


# ---------------------------------------------------------------------------
# タスク4.2: collect_site の検証
# ---------------------------------------------------------------------------


def test_collect_siteの検証_レジューム済みURLの場合_詳細取得を行わずスキップする(tmp_path):
    detail_url = "https://fake.example/detail/a"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    site = _FakeSite(listing_url_list=(listing_url,))
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    resume.mark_processed(detail_url)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    result = collect_site(
        site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
    )

    assert detail_url not in fetcher.text_calls
    assert site.detail_calls == []
    assert result.features == ()


def test_collect_siteの検証_範囲外都道府県の施設の場合_処理済み記録のみでスキップ集計しない(tmp_path):
    detail_url = "https://fake.example/detail/osaka"
    stub = SapaStub(display_name="大阪SA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    detail = _detail(name="大阪SA", address="大阪府大阪市北区1-1")
    site = _FakeSite(listing_url_list=(listing_url,), details_by_url={detail_url: detail})
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    result = collect_site(
        site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
    )

    assert resume.is_processed(detail_url) is True
    assert result.skipped_counts == {}
    assert result.features == ()
    assert partial_store.skipped_counts == {}
    assert geocoder.calls == []


def test_collect_siteの検証_直接座標がある場合_ジオコーディングを呼ばず直接座標を使う(tmp_path):
    detail_url = "https://fake.example/detail/direct-coord"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    direct_coordinate = Coordinate(longitude=139.1, latitude=35.1)
    detail = _detail(coordinate=direct_coordinate)
    site = _FakeSite(listing_url_list=(listing_url,), details_by_url={detail_url: detail})
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder(result=Coordinate(longitude=999.0, latitude=999.0))

    result = collect_site(
        site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
    )

    assert geocoder.calls == []
    assert len(result.features) == 1
    assert result.features[0].coordinate == direct_coordinate


def test_collect_siteの検証_直接座標がない場合_ジオコーディングで補完しINFOログを記録する(tmp_path, caplog):
    detail_url = "https://fake.example/detail/geocoded"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    detail = _detail(address="東京都新宿区西新宿1-1", coordinate=None)
    site = _FakeSite(listing_url_list=(listing_url,), details_by_url={detail_url: detail})
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoded_coordinate = Coordinate(longitude=139.7, latitude=35.7)
    geocoder = _FakeGeocoder(result=geocoded_coordinate)

    with caplog.at_level(logging.INFO, logger=_COLLECTOR_LOGGER_NAME):
        result = collect_site(
            site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
        )

    assert geocoder.calls == ["東京都新宿区西新宿1-1"]
    assert len(result.features) == 1
    assert result.features[0].coordinate == geocoded_coordinate
    assert result.geocoded_counts == {"13": 1}
    assert partial_store.geocoded_counts == {"13": 1}
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(detail_url in r.getMessage() for r in info_records)


def test_collect_siteの検証_路線名が欠落した施設の場合_unknownバケットでスキップする(tmp_path, caplog):
    detail_url = "https://fake.example/detail/no-road-name"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    detail = _detail(road_name=None)
    site = _FakeSite(listing_url_list=(listing_url,), details_by_url={detail_url: detail})
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    with caplog.at_level(logging.WARNING, logger=_COLLECTOR_LOGGER_NAME):
        result = collect_site(
            site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
        )

    assert result.features == ()
    assert result.skipped_counts == {"unknown": 1}
    assert partial_store.skipped_counts == {"unknown": 1}
    assert resume.is_processed(detail_url) is True
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(detail_url in r.getMessage() for r in warning_records)


def test_collect_siteの検証_詳細抽出がScrapingEngineErrorを送出した場合_unknownバケットでスキップする(tmp_path, caplog):
    detail_url = "https://fake.example/detail/structure-changed"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    site = _FakeSite(
        listing_url_list=(listing_url,),
        details_by_url={detail_url: StructureChangedError(detail_url, "h2")},
    )
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    with caplog.at_level(logging.WARNING, logger=_COLLECTOR_LOGGER_NAME):
        result = collect_site(
            site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
        )

    assert result.features == ()
    assert result.skipped_counts == {"unknown": 1}
    assert resume.is_processed(detail_url) is True
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(detail_url in r.getMessage() for r in warning_records)


def test_collect_siteの検証_住所がNoneで都道府県を特定できない場合_unknownバケットでスキップする(tmp_path):
    detail_url = "https://fake.example/detail/no-address"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    detail = _detail(address=None)
    site = _FakeSite(listing_url_list=(listing_url,), details_by_url={detail_url: detail})
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    result = collect_site(
        site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
    )

    assert result.features == ()
    assert result.skipped_counts == {"unknown": 1}
    assert resume.is_processed(detail_url) is True
    assert geocoder.calls == []


def test_collect_siteの検証_住所が都道府県名を含まない場合_unknownバケットでスキップする(tmp_path):
    detail_url = "https://fake.example/detail/unmatched-address"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    detail = _detail(address="不明な住所地1-1")
    site = _FakeSite(listing_url_list=(listing_url,), details_by_url={detail_url: detail})
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    result = collect_site(
        site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
    )

    assert result.features == ()
    assert result.skipped_counts == {"unknown": 1}
    assert resume.is_processed(detail_url) is True


def test_collect_siteの検証_座標を直接取得もジオコーディングでも解決できない場合_都道府県コードでスキップする(
    tmp_path, caplog
):
    detail_url = "https://fake.example/detail/no-coordinate"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    detail = _detail(address="東京都新宿区西新宿1-1", coordinate=None)
    site = _FakeSite(listing_url_list=(listing_url,), details_by_url={detail_url: detail})
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder(result=None)

    with caplog.at_level(logging.WARNING, logger=_COLLECTOR_LOGGER_NAME):
        result = collect_site(
            site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
        )

    assert result.features == ()
    assert result.skipped_counts == {"13": 1}
    assert partial_store.skipped_counts == {"13": 1}
    assert resume.is_processed(detail_url) is True
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(detail_url in r.getMessage() for r in warning_records)


def test_collect_siteの検証_一覧取得中にScrapingEngineErrorが発生した場合_SiteListingErrorをsite_key付きで送出する(
    tmp_path,
):
    listing_url = "https://fake.example/list"
    error = FetchFailedError(listing_url, 503, 3)
    site = _FakeSite(key="east", listing_url_list=(listing_url,))
    fetcher = _FakeFetcher(raise_by_url={listing_url: error})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    with pytest.raises(SiteListingError) as exc_info:
        collect_site(site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store)

    assert exc_info.value.site_key == "east"


def test_collect_siteの検証_一覧URLが0件の場合_エラーにせず空の結果を返す(tmp_path):
    site = _FakeSite(key="west", listing_url_list=())
    fetcher = _FakeFetcher()
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    result = collect_site(
        site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
    )

    assert result == SiteCollectResult(
        site_key="west", features=(), listed_urls=frozenset(), skipped_counts={}, geocoded_counts={}
    )


def test_collect_siteの検証_一覧URLはあるが施設を1件も確認できない場合_SiteListingErrorを送出する(tmp_path):
    listing_url = "https://fake.example/list"
    empty_listing_result = SapaListingResult(stubs=(), listed_urls=frozenset(), skipped_count=0)
    site = _FakeSite(key="central", listing_url_list=(listing_url,))
    fetcher = _FakeFetcher(json_by_url={listing_url: empty_listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder()

    with pytest.raises(SiteListingError) as exc_info:
        collect_site(site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store)

    assert exc_info.value.site_key == "central"


def test_collect_siteの検証_listing_kindがhtmlの場合_fetch_textとparse_htmlで一覧を取得する(tmp_path):
    listing_url = "https://fake.example/list.html"
    detail_url = "https://fake.example/detail/html-listing"
    stub = SapaStub(display_name="テストSA", detail_url=detail_url)
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    detail = _detail()
    site = _FakeSite(
        listing_kind="html",
        listing_url_list=(listing_url,),
        listing_by_url={listing_url: listing_result},
        details_by_url={detail_url: detail},
    )
    fetcher = _FakeFetcher(text_by_url={listing_url: "<html></html>"})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder(result=Coordinate(longitude=1.0, latitude=2.0))

    result = collect_site(
        site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
    )

    assert listing_url in fetcher.text_calls
    assert listing_url not in fetcher.json_calls
    assert len(result.features) == 1


def test_collect_siteの検証_成功した施設の場合_プロパティが正しくマッピングされ格納と処理済み記録が行われる(
    tmp_path,
):
    detail_url = "https://fake.example/detail/success"
    stub = SapaStub(display_name="テストSA(上り)", detail_url=detail_url)
    listing_url = "https://fake.example/list"
    listing_result = SapaListingResult(stubs=(stub,), listed_urls=frozenset({detail_url}), skipped_count=0)
    detail = _detail(name="テストSA", address="東京都新宿区西新宿1-1")
    site = _FakeSite(listing_url_list=(listing_url,), details_by_url={detail_url: detail})
    fetcher = _FakeFetcher(json_by_url={listing_url: listing_result})
    resume = _make_resume(tmp_path)
    partial_store = _make_partial_store(tmp_path)
    geocoder = _FakeGeocoder(result=Coordinate(longitude=139.7, latitude=35.7))

    result = collect_site(
        site, [_TOKYO], fetcher=fetcher, geocoder=geocoder, resume=resume, partial_store=partial_store
    )

    assert len(result.features) == 1
    feature = result.features[0]
    assert feature.properties.kind == FacilityKind.SAPA
    assert feature.properties.pref_code == "13"
    assert feature.properties.pref_name == "東京都"
    assert feature.properties.source_url == detail_url
    assert feature.properties.name == "テストSA"
    assert feature.properties.road_name == "テスト自動車道"
    assert any(f.properties.source_url == detail_url for f in partial_store.features)
    assert resume.is_processed(detail_url) is True
