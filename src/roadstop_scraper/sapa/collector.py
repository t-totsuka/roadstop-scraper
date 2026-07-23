"""サイト単位の収集ループと部分結果の逐次永続化。

1サイト分の一覧→詳細→座標解決→Feature化の収集ループ(``collect_site``)
と、実行横断の部分結果キャッシュ(``SapaPartialStore``)を提供するモジュール
(design.md「sapa.collector」節参照)。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from roadstop_scraper.common.logging_setup import get_logger
from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import (
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    Prefecture,
    from_feature_collection_dict,
    to_feature_collection_dict,
)
from roadstop_scraper.sapa.address import find_prefecture_by_address
from roadstop_scraper.sapa.geocoding import GsiGeocoder
from roadstop_scraper.sapa.sites import SapaSite
from roadstop_scraper.scraping import PageFetcher, ScrapingEngineError, UrlResumeTracker, parse_html

__all__ = ["SapaPartialStore", "SiteCollectResult", "SiteListingError", "collect_site"]

_logger = get_logger(__name__)

_UNKNOWN_PREFECTURE_BUCKET = "unknown"

_PARTIAL_STORE_KEY = "sapa-partial"
_PARTIAL_FEATURES_KEY = "features"
_PARTIAL_SKIPPED_COUNTS_KEY = "skipped_counts"
_PARTIAL_GEOCODED_COUNTS_KEY = "geocoded_counts"
_EMPTY_FEATURE_COLLECTION: dict[str, object] = {"type": "FeatureCollection", "features": []}


class SapaPartialStore:
    """実行横断(サイト横断・都道府県横断)の部分結果(成功済み``FacilityFeature``列・
    都道府県別スキップ件数・都道府県別ジオコーディング補完件数)を
    ``common.resume_store.ResumeStore``の単一キー``"sapa-partial"``へ逐次永続化する
    内部専用キャッシュ。

    design.md「sapa.collector」State Management: 05の``_PartialResultStore``と同じ
    「結果保存が先、mark_processedは後」という順序規律・「正常完了時のみクリア」
    規律を踏襲するが、収集単位が「サイト横断で収集→都道府県へ後段グルーピング」
    である06では都道府県単位ではなく実行全体で単一のキャッシュとし、件数も
    都道府県コード(または都道府県を特定できない場合の"unknown"バケット)別の
    マップとして保持する点が05と異なる(research.md Design Decisions「部分結果
    キャッシュは共通化せずsapa専用実装とする」参照)。

    ``sapa``パッケージの公開APIには含めない内部専用クラス。永続化する
    ``FacilityFeature``のJSON変換は、``geojson.to_feature_collection_dict``/
    ``from_feature_collection_dict``をそのまま再利用する最小実装で構わない。
    """

    def __init__(self, *, store: ResumeStore | None = None) -> None:
        """``store``(既定は新規``ResumeStore``)から部分結果を復元する。"""
        self._store = store if store is not None else ResumeStore()

        saved_state = self._store.load(_PARTIAL_STORE_KEY)
        if saved_state is None:
            self._features: list[FacilityFeature] = []
            self._skipped_counts: dict[str, int] = {}
            self._geocoded_counts: dict[str, int] = {}
        else:
            feature_collection = saved_state.get(_PARTIAL_FEATURES_KEY, _EMPTY_FEATURE_COLLECTION)
            self._features = from_feature_collection_dict(feature_collection)  # type: ignore[arg-type]
            self._skipped_counts = dict(saved_state.get(_PARTIAL_SKIPPED_COUNTS_KEY, {}))
            self._geocoded_counts = dict(saved_state.get(_PARTIAL_GEOCODED_COUNTS_KEY, {}))

    @property
    def features(self) -> list[FacilityFeature]:
        """これまでに確定した成功結果の複製を返す。"""
        return list(self._features)

    @property
    def skipped_counts(self) -> dict[str, int]:
        """都道府県コード(または"unknown")別のスキップ件数の複製を返す。"""
        return dict(self._skipped_counts)

    @property
    def geocoded_counts(self) -> dict[str, int]:
        """都道府県コード別のジオコーディング補完件数の複製を返す。"""
        return dict(self._geocoded_counts)

    def add_feature(self, feature: FacilityFeature) -> None:
        """1件の成功結果を追記し、状態全体を永続化する。

        同一``source_url``の既存結果は新しい結果で置き換える(本永続化と
        ``resume.mark_processed``の間でプロセスが中断された場合、再開時に同じ
        施設を再処理して再登録するため、追記を冪等にして二重登録を防ぐ)。
        """
        url = feature.properties.source_url
        self._features = [f for f in self._features if f.properties.source_url != url]
        self._features.append(feature)
        self._persist()

    def add_skip(self, pref_code: str | None) -> None:
        """1件のスキップを記録し、状態全体を永続化する。

        都道府県を特定できなかった場合(``pref_code``が``None``)は"unknown"
        バケットへ集計する(5.3)。
        """
        bucket = pref_code if pref_code is not None else _UNKNOWN_PREFECTURE_BUCKET
        self._skipped_counts[bucket] = self._skipped_counts.get(bucket, 0) + 1
        self._persist()

    def add_geocoded(self, pref_code: str) -> None:
        """1件のジオコーディング補完を記録し、状態全体を永続化する。"""
        self._geocoded_counts[pref_code] = self._geocoded_counts.get(pref_code, 0) + 1
        self._persist()

    def clear(self) -> None:
        """保持内容を空にし、永続化された状態も``ResumeStore``経由で削除する。"""
        self._features = []
        self._skipped_counts = {}
        self._geocoded_counts = {}
        self._store.clear(_PARTIAL_STORE_KEY)

    def _persist(self) -> None:
        """現在の成功結果・都道府県別件数の全体を``ResumeStore``へ保存する。"""
        self._store.save(
            _PARTIAL_STORE_KEY,
            {
                _PARTIAL_FEATURES_KEY: to_feature_collection_dict(self._features),
                _PARTIAL_SKIPPED_COUNTS_KEY: self._skipped_counts,
                _PARTIAL_GEOCODED_COUNTS_KEY: self._geocoded_counts,
            },
        )


class SiteListingError(Exception):
    """サイトの一覧取得が完全には成功しなかった(当該サイトを実行から除外する)。

    design.md「sapa.collector」Responsibilities: 一覧はサイトの全一覧URLの取得
    成功を要求し、1ページでも取得・パースに失敗(``ScrapingEngineError``)する、
    または一覧URLが1件以上存在するのに全体で``listed_urls``が空になる場合は
    サイト単位の失敗として扱う(2.3)。空一覧を正常扱いすると、後段の削除状態
    遷移(9.2)で前回出力の全施設が一斉に削除状態へ遷移してしまうため。
    """

    def __init__(self, site_key: str, cause: str) -> None:
        self.site_key = site_key
        """失敗したサイトの識別子("east" | "central" | "west")。"""

        self.cause = cause
        """失敗原因の説明文(ログ・上位への報告用)。"""

        super().__init__(f"サイト'{site_key}'の一覧取得に失敗しました: {cause}")


@dataclass(frozen=True)
class SiteCollectResult:
    """1回の``collect_site``呼び出し(1サイト分)の収集結果。

    設計上の注意(タスク4.2実装時の解釈): ``SapaPartialStore``は実行全体
    (サイト横断・都道府県横断)で単一の累積状態を持つが、本型が表すのは
    **この呼び出し(このサイト)自身が新たに収集した分のみ**であり、
    ``partial_store``の累積全体ではない。design.mdの「sapa.runner」
    Responsibilitiesが「成功サイトの結果を都道府県ごとにグルーピングし」と
    複数サイトの``SiteCollectResult``を横断集計する前提で書かれていること、
    および本型のフィールド名``site_key``が単一サイトへの帰属を明示している
    ことから、サイト単位の寄与分のみを返す解釈を採用した。
    """

    site_key: str
    """収集対象サイトの識別子。"""

    features: tuple[FacilityFeature, ...]
    """このサイト・この呼び出しで新たに確定した範囲内都道府県の成功結果。"""

    listed_urls: frozenset[str]
    """このサイトの一覧で存在確認できた全URL(スタブ化に失敗した分も含む)。"""

    skipped_counts: Mapping[str, int]
    """都道府県コード(または"unknown")別のスキップ件数(このサイト・この呼び出し分)。"""

    geocoded_counts: Mapping[str, int]
    """都道府県コード別のジオコーディング補完件数(このサイト・この呼び出し分)。"""


def collect_site(
    site: SapaSite,
    scope_prefectures: Sequence[Prefecture],
    *,
    fetcher: PageFetcher,
    geocoder: GsiGeocoder,
    resume: UrlResumeTracker,
    partial_store: SapaPartialStore,
) -> SiteCollectResult:
    """1サイト分の一覧→詳細→座標解決→Feature化の収集ループを実行する。

    design.md「sapa.collector」Responsibilities & Constraintsのとおり:

    1. 一覧: ``site.listing_urls(scope_prefectures)``で得た全URLの取得・パース
       成功を要求する。1ページでも``ScrapingEngineError``が発生した場合、または
       一覧URLが1件以上あるのに集約後の``listed_urls``が空になる場合は
       :class:`SiteListingError` を送出しサイト単位の失敗とする(2.3)。
       ``listing_urls``自体が空タプルを返す場合(対象範囲に当該サイトの管轄
       エリアが含まれない)は、失敗ではなく空の``SiteCollectResult``を返す。
    2. 詳細ループ: 未処理スタブのみ取得(7.1)→``extract_detail``→必須項目検査
       (road_name欠落は5.1のスキップ)→住所分離→都道府県導出(不可なら5.1の
       スキップ)→範囲外なら処理済み記録のみ→座標解決(4.1優先、無ければ
       ジオコーディング、両方不可でスキップ=4.3)→``FacilityProperties``構築
       (3.5)→部分結果保存→``mark_processed``(7.2、結果保存が先の順序)。
    3. スキップは対象URLを含むWARNINGログと都道府県別件数(都道府県導出前は
       "unknown"バケット)へ記録し、個々の失敗で処理を止めない(5.1-5.3)。
       スキップした施設も``mark_processed``し、同一の中断・再開サイクル内での
       無駄な再試行を避ける(7.2、design.mdエラーハンドリング表と同一の規律)。

    戻り値の``SiteCollectResult``はこの呼び出し(このサイト)自身が新たに収集
    した分のみを表す(``partial_store``の累積全体ではない。上記型のdocstring
    参照)。``partial_store``へは施設1件が確定するたびに逐次追記・永続化する
    (中断・再開時の取りこぼし防止)。
    """
    listing_url_list = site.listing_urls(scope_prefectures)
    if not listing_url_list:
        # 対象範囲に当該サイトの管轄エリアが含まれない場合の正常な「収集対象
        # なし」。listing_urls自体が0件なのは失敗ではない(design.md参照)。
        return SiteCollectResult(
            site_key=site.key,
            features=(),
            listed_urls=frozenset(),
            skipped_counts={},
            geocoded_counts={},
        )

    stubs: list = []
    aggregated_listed_urls: set[str] = set()
    for listing_url in listing_url_list:
        try:
            if site.listing_kind == "html":
                fetched = fetcher.fetch_text(listing_url)
                page = parse_html(fetched.text, fetched.url)
                listing_result = site.parse_listing(page)
            else:
                data = fetcher.fetch_json(listing_url)
                listing_result = site.parse_listing(data)
        except ScrapingEngineError as error:
            # 2.3: 一覧の1ページでも取得・パースに失敗した場合は、当該サイトの
            # 他の一覧URLの処理を続けず、直ちにサイト単位の失敗として通知する。
            raise SiteListingError(
                site.key,
                f"一覧URL '{listing_url}' の取得に失敗しました: {error}",
            ) from error

        stubs.extend(listing_result.stubs)
        aggregated_listed_urls.update(listing_result.listed_urls)

    if not aggregated_listed_urls:
        # 一覧URLは1件以上存在したが、全ページを通じて施設を1件も確認できな
        # かった場合。空を正常扱いすると9.2で前回出力の全施設が一斉に削除状態
        # へ遷移するため、サイト単位の失敗として扱う(michinoeki/listing.pyの
        # ListingUnavailableErrorと同じ判断)。
        raise SiteListingError(
            site.key,
            f"一覧URLは{len(listing_url_list)}件存在しますが、施設を1件も確認できませんでした",
        )

    scope_codes = {prefecture.code for prefecture in scope_prefectures}
    features: list[FacilityFeature] = []
    skipped_counts: dict[str, int] = {}
    geocoded_counts: dict[str, int] = {}

    def _record_skip(pref_code: str | None) -> None:
        bucket = pref_code if pref_code is not None else _UNKNOWN_PREFECTURE_BUCKET
        skipped_counts[bucket] = skipped_counts.get(bucket, 0) + 1
        partial_store.add_skip(pref_code)

    for stub in stubs:
        if resume.is_processed(stub.detail_url):
            # 7.1: 既に処理済み。詳細取得すら行わず、成功・スキップいずれの
            # 集計にも含めない(同一の中断・再開サイクル内での再取得を防ぐ)。
            continue

        try:
            fetched = fetcher.fetch_text(stub.detail_url)
            page = parse_html(fetched.text, fetched.url)
            detail = site.extract_detail(page, stub.detail_url)
        except ScrapingEngineError as error:
            # extract_detail内のStructureChangedError(名称欠落等)も含め、
            # 個々の施設の抽出失敗はサイト全体を中断させずスキップする。
            _logger.warning(
                "SA/PA詳細の抽出に失敗したためスキップ: url=%s error=%s",
                stub.detail_url,
                error,
            )
            _record_skip(None)
            resume.mark_processed(stub.detail_url)
            continue

        if not detail.road_name:
            # 5.1: 必須項目(路線名)欠落。名称は extract_detail 自身の契約で
            # 非空が保証される(欠落時はStructureChangedErrorで上のブロックへ
            # 合流する)ため、ここでの必須項目検査は路線名のみでよい。
            _logger.warning(
                "路線名を取得できないためスキップ: url=%s",
                stub.detail_url,
            )
            _record_skip(None)
            resume.mark_processed(stub.detail_url)
            continue

        # 各サイトアダプタ(east/central/west)はSapaDetailを構築する時点で
        # 既に住所本体と郵便番号を分離済み(east.py/central.py/west.pyの
        # _split_address参照)のため、ここで住所本体へ再度split_postal_address
        # を適用してはならない(再分離対象は既に郵便番号を含まないため常に
        # 不一致となり、detail.postal_codeが握り潰されてpostal_codeが常に
        # Noneになるバグを過去に埋め込んでいた)。address_body/postal_codeは
        # detail側の値をそのまま使う。
        prefecture: Prefecture | None = None
        address_body: str | None = detail.address
        postal_code: str | None = detail.postal_code
        if detail.address is not None:
            prefecture = find_prefecture_by_address(detail.address)

        if prefecture is None:
            # 3.6: 所在都道府県を特定できない場合は抽出失敗として扱う。
            _logger.warning(
                "所在都道府県を特定できないためスキップ: url=%s address=%r",
                stub.detail_url,
                detail.address,
            )
            _record_skip(None)
            resume.mark_processed(stub.detail_url)
            continue

        if prefecture.code not in scope_codes:
            # 範囲外の施設は処理済み記録のみで、スキップ集計・座標解決・
            # 出力対象のいずれにも含めない(design.md「範囲外施設の扱い」)。
            resume.mark_processed(stub.detail_url)
            continue

        if detail.coordinate is not None:
            # 4.1: サイト直接値を優先し、ジオコーディングは呼ばない。
            coordinate = detail.coordinate
        else:
            # 4.2: 直接座標が無い場合のみ住所からジオコーディングで補完する。
            coordinate = geocoder.geocode(address_body) if address_body else None
            if coordinate is not None:
                geocoded_counts[prefecture.code] = geocoded_counts.get(prefecture.code, 0) + 1
                partial_store.add_geocoded(prefecture.code)
                # 4.4: GsiGeocoder.geocode自体はURLを受け取れないため、施設URL
                # を保持するこの呼び出し元でURL込みのINFOログを記録する
                # (tasks.md Implementation Notes、タスク2.2の既知の制約を解消)。
                _logger.info(
                    "座標をジオコーディングで補完: url=%s address=%s longitude=%s latitude=%s",
                    stub.detail_url,
                    address_body,
                    coordinate.longitude,
                    coordinate.latitude,
                )

        if coordinate is None:
            # 4.3: 直接取得もジオコーディングでの補完もできない場合は抽出失敗
            # として扱う。この時点で都道府県は判明済みのため、"unknown"では
            # なく実際の都道府県コードで集計する。
            _logger.warning(
                "座標を直接取得もジオコーディングでも解決できないためスキップ: url=%s prefecture=%s",
                stub.detail_url,
                prefecture.name_ja,
            )
            skipped_counts[prefecture.code] = skipped_counts.get(prefecture.code, 0) + 1
            partial_store.add_skip(prefecture.code)
            resume.mark_processed(stub.detail_url)
            continue

        properties = FacilityProperties(
            name=detail.name,
            kind=FacilityKind.SAPA,
            pref_code=prefecture.code,
            pref_name=prefecture.name_ja,
            address=address_body,
            postal_code=postal_code,
            tel=detail.tel,
            opening_hours=detail.opening_hours,
            parking=detail.parking,
            websites=detail.websites,
            source_url=stub.detail_url,
            facilities=detail.facilities,
            road_name=detail.road_name,
            direction=detail.direction,
            area_direction=detail.area_direction,
        )
        feature = FacilityFeature(coordinate=coordinate, properties=properties)
        features.append(feature)
        # 7.2: 結果の永続化(add_feature)を先に行い、その後にmark_processed
        # を呼ぶ(05と同じ順序規律。逆順だと両永続化の間の中断で「処理済みだが
        # 結果未保存」となり、当該施設が今回サイクルの出力から漏れる)。
        partial_store.add_feature(feature)
        resume.mark_processed(stub.detail_url)

    return SiteCollectResult(
        site_key=site.key,
        features=tuple(features),
        listed_urls=frozenset(aggregated_listed_urls),
        skipped_counts=skipped_counts,
        geocoded_counts=geocoded_counts,
    )
