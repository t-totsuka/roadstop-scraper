"""削除状態管理とサイト失敗隔離の結合検証(タスク6.1)。

``tests/sapa/test_runner.py``のタスク5.1/5.2向けテストは``run_prefecture``/
``run_prefectures``/``run_scope``のオーケストレーション自体は実際のコードを
通すが、``SapaSite``プロトコルを満たす偽サイト(``_FakeSite``/
``_RunScopeFakeSite``)を使っており、``parse_listing``/``extract_detail``は
事前登録した結果をそのまま返すだけで、実際のHTML/JSON解析は一切行われない
(``tests/sapa/test_collector.py``の``_FakeSite``も同様)。そのため、実際の
サイトアダプタ(``EastSite``/``CentralSite``/``WestSite``)の一覧・詳細
パースロジックが``run_scope``経由で正しく配線されていること――特に
``owns_url``によるサイト帰属判定(サイト失敗隔離の核心)が実装済みの
``EastSite.owns_url``/``CentralSite.owns_url``の実際の挙動と整合すること
――は、5.1/5.2のテストでは一切検証されていなかった(本タスクの`_Boundary:_`
「削除状態・サイト隔離の結合テスト専用ファイル」が要求する監査の結果)。

本ファイルは、``tests/michinoeki/test_runner.py``が確立した偽セッション
(``SessionLike``を満たす``_FakeSession``/``_FakeResponse``)パターンを踏襲し、
実際の``PageFetcher``へ偽セッションを注入する形で、``run_scope``→(実際の)
``ALL_SITES``(``EastSite``・``CentralSite``・``WestSite``の実インスタンス、
モンキーパッチなし)→``collect_site``→サイトアダプタの実際の
``parse_listing``/``extract_detail``→``merge_with_previous``→実際の
``write_geojson``という全経路を、最小限のフィクスチャHTMLで検証する。

検証する5つの観測可能な事象(design.md「Testing Strategy」Integration Tests・
Requirements 9.1-9.4, 2.3):

1. 削除遷移(9.2): 前回出力に存在した施設が今回の一覧に一切現れない場合、
   ``status=DELETED``へ遷移し``last_confirmed_at``は前回のまま変わらない。
2. 再出現復帰(9.3): 前回``DELETED``だった施設が今回の一覧に再び現れ詳細
   抽出も成功する場合、``status=ACTIVE``へ戻り``last_confirmed_at``が
   今回の``confirmed_at``へ更新される。
3. 1年経過の完全除去(9.4): 前回``DELETED``かつ``last_confirmed_at``が
   ``confirmed_at``から365日超過している施設は、出力から完全に除去される。
4. 一覧に実在するが抽出失敗した施設の現状維持(9.2の裏側・2.3の精神):
   一覧には存在する(``listed_urls``に含まれる)が詳細抽出に失敗した施設は、
   前回の状態(``status``・``last_confirmed_at``とも)がそのまま維持される。
5. サイト一覧失敗時の当該サイト施設の一斉削除防止(2.3): あるサイトの一覧
   取得が失敗しても、他サイトの収集(実際のアダプタの一覧・詳細解析を含む)
   は継続され、失敗サイト帰属の前回施設は削除判定から除外されて現状維持の
   まま出力される。

1・2・3・4は``EastSite``単独(東京都)で、5は``EastSite``
(成功)と``CentralSite``(一覧取得失敗)の2サイトが同時に関与する長野県
(``prefecture_code="20"``、``EastSite``の管轄(東日本管内全域)・``CentralSite``の
両管轄が交差する)で検証する。``WestSite``は本ファイルのいずれの対象都道府県
とも管轄が交差しないため(``_WEST_PREFECTURE_CODES``参照)、実際に
``ALL_SITES``へ含まれ``listing_urls``が呼ばれはするが、空タプルを返して
HTTPリクエストは発生しない(正常な「収集対象なし」経路)。
"""

from __future__ import annotations

from datetime import UTC, datetime

from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import (
    Coordinate,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    FacilityStatus,
    Prefecture,
    build_geojson_filename,
    find_prefecture,
    read_geojson,
    write_geojson,
)
from roadstop_scraper.pipeline import ScopeSpec
from roadstop_scraper.sapa.collector import SapaPartialStore
from roadstop_scraper.sapa.runner import SapaPrefectureResult, SapaScopeRunResult, run_scope
from roadstop_scraper.scraping import PageFetcher, ScrapingConfig, UrlResumeTracker

_CONFIRMED_AT = datetime(2026, 7, 19, 9, 0, 0, tzinfo=UTC)
_PREVIOUS_CONFIRMED_AT = datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)
_RETENTION_EXCEEDED_CONFIRMED_AT = datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)

_TOKYO = find_prefecture("13")
_NAGANO = find_prefecture("20")


class _FakeResponse:
    """``ResponseLike``を満たす偽レスポンス(michinoeki/test_runner.pyと同じ形)。"""

    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.apparent_encoding = "utf-8"


class _FakeSession:
    """URLに応じてHTML応答(または登録された失敗ステータス)を返す偽セッション。

    HTTP層のみをスタブ化し、``fetch_text``→``parse_html``→
    ``site.parse_listing``/``extract_detail``という以降の経路は実際の
    コンポーネントのまま通す(michinoeki/test_runner.pyの``_FakeSession``/
    ``_FakeSessionWithFailures``と同じ方針)。
    """

    def __init__(
        self,
        html_by_url: dict[str, str],
        *,
        failure_status_by_url: dict[str, int] | None = None,
    ) -> None:
        self._html_by_url = html_by_url
        self._failure_status_by_url = failure_status_by_url or {}
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> _FakeResponse:
        self.calls.append(url)
        if url in self._failure_status_by_url:
            return _FakeResponse(self._failure_status_by_url[url], b"", headers={})
        html = self._html_by_url[url]
        return _FakeResponse(200, html.encode("utf-8"), headers={"Content-Type": "text/html; charset=utf-8"})


class _FakeGeocoder:
    """住所によらず固定の座標を返す偽ジオコーダー。

    ``EastSite.extract_detail``は常に``coordinate=None``を返す実装のため
    (4.1の直接座標が存在しない実サイトの実測どおり)、東日本の全施設が
    ジオコーディング(4.2)経由となる。本テストの主眼は座標補完自体
    (``sapa.geocoding``の担当、既存テストで検証済み)ではなく削除状態管理・
    サイト失敗隔離の結合経路のため、実際のGSI APIへは疎通せず固定座標を返す
    最小限の偽物で足りる(``tests/sapa/test_runner.py``の``_RunScopeFakeGeocoder``
    と同じ方針)。
    """

    def __init__(self, result: Coordinate) -> None:
        self._result = result
        self.calls: list[str] = []

    def geocode(self, address: str) -> Coordinate | None:
        self.calls.append(address)
        return self._result


def _fast_config() -> ScrapingConfig:
    return ScrapingConfig(
        timeout_seconds=5.0,
        max_retries=0,
        retry_wait_seconds=0.0,
        min_request_interval_seconds=0.0,
    )


def _sapa_feature(
    *,
    name: str,
    source_url: str,
    pref: Prefecture,
    status: FacilityStatus,
    last_confirmed_at: datetime,
) -> FacilityFeature:
    return FacilityFeature(
        coordinate=Coordinate(longitude=139.0, latitude=35.0),
        properties=FacilityProperties(
            name=name,
            kind=FacilityKind.SAPA,
            pref_code=pref.code,
            pref_name=pref.name_ja,
            source_url=source_url,
            status=status,
            last_confirmed_at=last_confirmed_at,
        ),
    )


# 東日本(driveplaza.com)の一覧URL。タスク6.3の実サイト疎通確認で、arealistは
# HIGHWAY=AA併用時に値によらず東日本管内全域を返すことが判明したため、
# EastSite.listing_urlsは東京都・長野県のいずれの単独指定でも同一の単一URL
# (arealist=0)を返す(east.py._LISTING_URL_TEMPLATEと同じ構成。実装を直接
# importせず、実サイトのURL構成を模したフィクスチャとして独立に構成する)。
_EAST_TOKYO_LISTING_URL = "https://www.driveplaza.com/dp/SAPAServRes?arealist=0&HIGHWAY=AA"
_EAST_NAGANO_LISTING_URL = "https://www.driveplaza.com/dp/SAPAServRes?arealist=0&HIGHWAY=AA"
_CENTRAL_SEARCH_URL = "https://sapa.c-nexco.co.jp/search/result"


def _east_listing_html(entries: list[tuple[str, str]]) -> str:
    """(表示名, 詳細URL)列から``div.box-sapa``要素群を持つ一覧HTMLを生成する(east.pyの実測構造)。"""
    boxes = "\n".join(
        f'<div class="box-sapa"><h3 class="ttl-sapaName"><a href="{href}">{name}</a></h3></div>'
        for name, href in entries
    )
    return f"<html><body><main>{boxes}</main></body></html>"


def _east_detail_html(*, name: str, road_name: str, address: str) -> str:
    """east.pyのテンプレートA構造を模した詳細ページHTML(実測に基づくフィクスチャ)。"""
    return f"""
<html>
  <body>
    <div class="title-wrap">
      <span class="txt-way">{road_name}</span>
      <h1 class="c-titleH1 has-ruby"><span class="txt-title">{name}</span></h1>
      <span class="c-labelRight">上り</span>
    </div>
    <div class="box-facility">
      <div class="box-info">
        <p>{address}</p>
      </div>
    </div>
  </body>
</html>
"""


# 名称を解決できるセレクタ(テンプレートA・テンプレートBいずれの見出しも)が
# 一切存在しないHTML。EastSite.extract_detailはテンプレートA→Bの順に試みても
# 名称を解決できず、require_textの自然な送出によりStructureChangedErrorとなる
# (構造変化・抽出失敗のフィクスチャ)。
_EAST_STRUCTURE_CHANGED_HTML = "<html><body><p>ページが見つかりません</p></body></html>"


def _make_resume_and_partial(tmp_path, key: str) -> tuple[UrlResumeTracker, SapaPartialStore]:
    store = ResumeStore(state_dir=tmp_path / ".resume")
    return UrlResumeTracker(key, store=store), SapaPartialStore(store=store)


def test_削除状態遷移の結合検証_実サイトアダプタ経由で削除復帰完全除去と抽出失敗時の現状維持が一貫して動作する(
    tmp_path,
):
    """1(削除遷移)・2(再出現復帰)・3(1年経過の完全除去)・4(現状維持)を、
    実際の``EastSite``(東京都)が一覧HTML→詳細HTMLを実際に
    パースする経路で、単一の``run_scope``呼び出しにより検証する。
    """
    reactivate_url = "https://www.driveplaza.com/sapa/1010/1010001/1/"
    structure_changed_url = "https://www.driveplaza.com/sapa/1010/1010002/1/"
    deletion_candidate_url = "https://www.driveplaza.com/sapa/1010/1010003/1/"
    purge_candidate_url = "https://www.driveplaza.com/sapa/1010/1010004/1/"

    # 今回の一覧には再出現施設・構造変化施設の2件のみが実在する(削除候補・
    # 完全除去候補は一覧からも一切消失している状況を表す)。
    html_by_url = {
        _EAST_TOKYO_LISTING_URL: _east_listing_html(
            [
                ("テスト東京SA(上り)", reactivate_url),
                ("テスト構造変化SA(上り)", structure_changed_url),
            ]
        ),
        reactivate_url: _east_detail_html(
            name="テスト東京SA", road_name="首都高速道路", address="東京都千代田区丸の内1-1"
        ),
        structure_changed_url: _EAST_STRUCTURE_CHANGED_HTML,
    }
    session = _FakeSession(html_by_url)
    fetcher = PageFetcher(_fast_config(), session=session)
    geocoder = _FakeGeocoder(result=Coordinate(longitude=139.75, latitude=35.68))
    resume, partial_store = _make_resume_and_partial(tmp_path, "sapa-test-integration-deletion")
    output_dir = tmp_path / "geo-json"

    # 前回出力: 再出現施設(DELETED)・構造変化施設(ACTIVE)・削除候補(ACTIVE)・
    # 完全除去候補(DELETED・保持期間超過)の4件。
    previous_features = [
        _sapa_feature(
            name="テスト東京SA(旧)",
            source_url=reactivate_url,
            pref=_TOKYO,
            status=FacilityStatus.DELETED,
            last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
        ),
        _sapa_feature(
            name="テスト構造変化SA",
            source_url=structure_changed_url,
            pref=_TOKYO,
            status=FacilityStatus.ACTIVE,
            last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
        ),
        _sapa_feature(
            name="テスト削除候補SA",
            source_url=deletion_candidate_url,
            pref=_TOKYO,
            status=FacilityStatus.ACTIVE,
            last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
        ),
        _sapa_feature(
            name="テスト完全除去候補SA",
            source_url=purge_candidate_url,
            pref=_TOKYO,
            status=FacilityStatus.DELETED,
            last_confirmed_at=_RETENTION_EXCEEDED_CONFIRMED_AT,
        ),
    ]
    filename = build_geojson_filename(_TOKYO, FacilityKind.SAPA)
    write_geojson(previous_features, filename, output_dir=output_dir)

    # ALL_SITESはモンキーパッチしない(実際のEastSite/CentralSite/WestSiteを
    # そのまま使う。本テストの核心=実アダプタでの結合検証)。
    result = run_scope(
        ScopeSpec(prefecture_code="13"),
        fetcher=fetcher,
        geocoder=geocoder,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_store,
    )

    assert isinstance(result, SapaScopeRunResult)
    assert result.failed_site_keys == frozenset()
    assert result.failed_prefecture_codes == frozenset()
    assert len(result.prefecture_results) == 1
    pref_result = result.prefecture_results[0]
    assert isinstance(pref_result, SapaPrefectureResult)

    # 実際のHTTP層(偽セッション)への呼び出しが、一覧→両詳細ページの順で
    # 実際に発生していることを確認する(実アダプタが実際に解析を行った証跡)。
    assert session.calls == [_EAST_TOKYO_LISTING_URL, reactivate_url, structure_changed_url]

    written = read_geojson(output_dir / filename)
    by_url = {f.properties.source_url: f for f in written}

    # 3: 保持期間超過の完全除去候補は出力から完全に消える。
    assert purge_candidate_url not in by_url
    assert set(by_url) == {reactivate_url, structure_changed_url, deletion_candidate_url}

    # 2: 再出現復帰。実際にextract_detailが成功し名称が反映されていることも
    # あわせて確認する(実解析の証跡)。
    reactivated = by_url[reactivate_url]
    assert reactivated.properties.status is FacilityStatus.ACTIVE
    assert reactivated.properties.last_confirmed_at == _CONFIRMED_AT
    assert reactivated.properties.name == "テスト東京SA"
    assert reactivated.properties.road_name == "首都高速道路"

    # 4: 一覧には実在するが詳細抽出(構造変化)に失敗した施設は前回状態のまま
    # (statusもlast_confirmed_atも変化しない)。
    unchanged = by_url[structure_changed_url]
    assert unchanged.properties.status is FacilityStatus.ACTIVE
    assert unchanged.properties.last_confirmed_at == _PREVIOUS_CONFIRMED_AT

    # 1: 一覧から完全に消失した施設は削除状態へ遷移する(last_confirmed_atは
    # 前回のまま)。
    deleted = by_url[deletion_candidate_url]
    assert deleted.properties.status is FacilityStatus.DELETED
    assert deleted.properties.last_confirmed_at == _PREVIOUS_CONFIRMED_AT

    assert pref_result.scraped_count == 1
    # 構造変化によるスキップは(路線名欠落によるスキップ等と同様に)都道府県
    # 導出前に確定するため"unknown"バケットに集計され、都道府県別の
    # skipped_countには計上されない(runner._aggregate_counts_by_prefectureの
    # 仕様どおり。design.mdのCONCERNS参照)。
    assert pref_result.skipped_count == 0
    assert pref_result.reactivated_count == 1
    assert pref_result.newly_deleted_count == 1
    assert pref_result.purged_count == 1


def test_サイト失敗隔離の結合検証_実サイトアダプタ経由で中日本の一覧取得失敗時に東日本の収集は継続し中日本の前回施設は現状維持される(
    tmp_path,
):
    """5(サイト一覧失敗時の当該サイト施設の一斉削除防止)を、実際の
    ``EastSite``(長野県、成功)と実際の``CentralSite``
    (一覧取得がHTTP 500で失敗)が同一``run_scope``呼び出しで同時に関与する
    長野県で検証する。``owns_url``によるサイト帰属判定(``EastSite``は
    ``driveplaza.com``系ホスト、``CentralSite``は``sapa.c-nexco.co.jp``の
    実際の実装)が正しく機能することが本テストの核心であり、``tests/sapa/
    test_runner.py``の同種テストは``owns_url``をURLプレフィックス一致のみで
    済ませる偽サイトを使っていたため、実アダプタでの検証はここが初めてとなる。
    """
    reactivate_url_east = "https://www.driveplaza.com/sapa/2020/2020001/1/"
    central_previous_url = "https://sapa.c-nexco.co.jp/sapa?sapainfoid=501"

    html_by_url = {
        _EAST_NAGANO_LISTING_URL: _east_listing_html([("テスト長野SA(上り)", reactivate_url_east)]),
        reactivate_url_east: _east_detail_html(
            name="テスト長野SA", road_name="長野自動車道", address="長野県松本市白板1-1"
        ),
    }
    session = _FakeSession(html_by_url, failure_status_by_url={_CENTRAL_SEARCH_URL: 500})
    fetcher = PageFetcher(_fast_config(), session=session)
    geocoder = _FakeGeocoder(result=Coordinate(longitude=137.97, latitude=36.24))
    resume, partial_store = _make_resume_and_partial(tmp_path, "sapa-test-integration-site-failure")
    output_dir = tmp_path / "geo-json"

    # 前回出力: 東日本帰属(再出現候補・DELETED)と中日本帰属(ACTIVE)の2件。
    previous_features = [
        _sapa_feature(
            name="テスト長野SA(旧)",
            source_url=reactivate_url_east,
            pref=_NAGANO,
            status=FacilityStatus.DELETED,
            last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
        ),
        _sapa_feature(
            name="テスト中日本施設",
            source_url=central_previous_url,
            pref=_NAGANO,
            status=FacilityStatus.ACTIVE,
            last_confirmed_at=_PREVIOUS_CONFIRMED_AT,
        ),
    ]
    filename = build_geojson_filename(_NAGANO, FacilityKind.SAPA)
    write_geojson(previous_features, filename, output_dir=output_dir)

    result = run_scope(
        ScopeSpec(prefecture_code="20"),
        fetcher=fetcher,
        geocoder=geocoder,
        resume=resume,
        confirmed_at=_CONFIRMED_AT,
        output_dir=output_dir,
        partial_result_store=partial_store,
    )

    assert isinstance(result, SapaScopeRunResult)
    # 中日本の一覧取得失敗(実際のCentralSite.listing_kind == "html"のfetch_text
    # がHTTP 500でFetchFailedErrorとなり、collect_siteがSiteListingErrorへ変換)。
    assert result.failed_site_keys == frozenset({"central"})
    # 長野県自体の出力は成功する(検証違反・前回ファイル破損なし)。
    assert result.failed_prefecture_codes == frozenset()

    # 実際のHTTP層への呼び出し: 東日本の一覧→詳細、中日本の一覧(失敗)の順
    # (ALL_SITESの登録順east→central→westのうち、east成功・central失敗・
    # westは管轄外のためHTTPリクエスト自体が発生しない)。
    assert session.calls == [_EAST_NAGANO_LISTING_URL, reactivate_url_east, _CENTRAL_SEARCH_URL]

    written = read_geojson(output_dir / filename)
    by_url = {f.properties.source_url: f for f in written}

    # 東日本帰属施設は通常どおり削除状態遷移の完全経路(再出現復帰)を通る。
    east_feature = by_url[reactivate_url_east]
    assert east_feature.properties.status is FacilityStatus.ACTIVE
    assert east_feature.properties.last_confirmed_at == _CONFIRMED_AT
    assert east_feature.properties.name == "テスト長野SA"

    # 5の核心: 一覧取得に失敗した中日本帰属の前回施設は、今回の一覧・収集結果に
    # 一切現れないにもかかわらず、削除判定から除外され現状維持のまま出力される
    # (status・last_confirmed_atとも一切変化しない)。
    central_feature = by_url[central_previous_url]
    assert central_feature.properties.status is FacilityStatus.ACTIVE
    assert central_feature.properties.last_confirmed_at == _PREVIOUS_CONFIRMED_AT

    pref_result = result.prefecture_results[0]
    assert isinstance(pref_result, SapaPrefectureResult)
    assert pref_result.scraped_count == 1
    assert pref_result.reactivated_count == 1
    # 中日本帰属施設はmerge_with_previousの入力にすら含まれないため、削除
    # 遷移カウントには一切計上されない。
    assert pref_result.newly_deleted_count == 0
    assert pref_result.purged_count == 0
