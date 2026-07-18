"""都道府県単位・範囲単位のオーケストレーション(runner)。

本モジュールはタスク5.1〜5.4にわたって段階的に構築される。タスク5.1で、
一覧取得済みの``StationStub``列を基に未処理の道の駅のみ詳細抽出し、成功結果と
スキップ件数を蓄積する収集ループ(design.md「都道府県単位の実行フロー」
flowchart F〜J)を実装した。タスク5.2では、この収集ループへ一覧取得・前回
GeoJSONとのマージ・出力・``index.json``更新を統合した公開関数``run_prefecture``
を追加した(flowchart D〜O)。タスク5.3では、中断・再開をまたいだ都道府県単位
の部分結果キャッシュ(``_PartialResultStore``)を追加し、都道府県処理の途中で
中断されても中断前の成功結果・スキップ件数を失わずに再開できるようにする
(flowchart D2・I・J・N・O)。タスク5.4では、``resolve_scope``で解決した対象
都道府県列を順に``run_prefecture``へ渡す範囲全体のオーケストレーション
(``run_scope``)を追加した。都道府県単位の失敗があってもループを継続し、
指定範囲の全都道府県が完了した場合にのみ``resume.clear()``を呼ぶ
(flowchart A〜C・P、6.3)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from python_util import time_utility
from roadstop_scraper.common import index_store
from roadstop_scraper.common.logging_setup import get_logger, log_scrape_finished, log_scrape_started
from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import (
    DEFAULT_OUTPUT_DIR,
    FacilityFeature,
    FacilityKind,
    GeoJsonValidationError,
    Prefecture,
    build_geojson_filename,
    from_feature_collection_dict,
    read_geojson,
    to_feature_collection_dict,
    write_geojson,
)
from roadstop_scraper.michinoeki.detail import extract_station_properties
from roadstop_scraper.michinoeki.listing import fetch_station_stubs
from roadstop_scraper.michinoeki.merge import merge_with_previous
from roadstop_scraper.michinoeki.scope import ScopeSpec, resolve_scope
from roadstop_scraper.scraping import (
    PageFetcher,
    ScrapingEngineError,
    UrlResumeTracker,
    load_scraping_config,
    parse_html,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from roadstop_scraper.michinoeki.listing import StationStub

__all__ = ["PrefectureRunResult", "run_prefecture", "run_scope"]

_logger = get_logger(__name__)

_PARTIAL_FEATURES_KEY = "features"
_PARTIAL_SKIPPED_COUNT_KEY = "skipped_count"
_EMPTY_FEATURE_COLLECTION: dict[str, object] = {"type": "FeatureCollection", "features": []}


class _PartialResultStore:
    """都道府県単位の部分抽出結果(成功済み``FacilityFeature``列・スキップ件数)を
    ``common.resume_store.ResumeStore``へ逐次永続化する内部専用キャッシュ。

    design.md「都道府県単位の部分抽出結果の永続化」: ``UrlResumeTracker``はURL
    単位の処理済みフラグのみを永続化し、抽出済みの``FacilityProperties``自体は
    保持しない。都道府県の処理途中で中断された場合にこれを失わないよう、道の駅
    1件の処理(成功/失敗)が確定するたびに``add_feature``/``add_skip``で逐次
    追記・永続化する。都道府県処理の開始時に読み込んで復元し、``write_geojson``・
    ``index_store``更新が正常完了した後にのみ``clear``で消去する(消去前に
    プロセスが中断されても、次回起動時に同じキャッシュから正しく再開できる)。

    ``michinoeki``パッケージの公開APIには含めない内部専用クラス。永続化する
    ``FacilityFeature``のJSON変換は、``geojson.to_feature_collection_dict``/
    ``from_feature_collection_dict``をそのまま再利用する最小実装で構わない
    (design.md Implementation Notes、消費側フォーマットとの整合は不要)。
    """

    def __init__(self, prefecture: Prefecture, *, store: ResumeStore | None = None) -> None:
        """``prefecture``に対応する部分結果を``store``から復元する(既定は新規``ResumeStore``)。"""
        self._key = f"michinoeki-partial-{prefecture.code}"
        self._store = store if store is not None else ResumeStore()

        saved_state = self._store.load(self._key)
        if saved_state is None:
            self._features: list[FacilityFeature] = []
            self._skipped_count = 0
        else:
            feature_collection = saved_state.get(_PARTIAL_FEATURES_KEY, _EMPTY_FEATURE_COLLECTION)
            self._features = from_feature_collection_dict(feature_collection)  # type: ignore[arg-type]
            self._skipped_count = int(saved_state.get(_PARTIAL_SKIPPED_COUNT_KEY, 0))

    @property
    def features(self) -> list[FacilityFeature]:
        """これまでに確定した成功結果の複製を返す。"""
        return list(self._features)

    @property
    def skipped_count(self) -> int:
        """これまでに確定したスキップ件数を返す。"""
        return self._skipped_count

    def add_feature(self, feature: FacilityFeature) -> None:
        """1件の道の駅の成功結果を追記し、状態全体を永続化する。

        同一``source_url``の既存結果は新しい結果で置き換える(本永続化と
        ``resume.mark_processed``の間でプロセスが中断された場合、再開時に同じ
        道の駅を再処理して再登録するため、追記を冪等にして二重登録を防ぐ)。
        """
        url = feature.properties.source_url
        self._features = [f for f in self._features if f.properties.source_url != url]
        self._features.append(feature)
        self._persist()

    def add_skip(self) -> None:
        """1件の道の駅のスキップを記録し、状態全体を永続化する。"""
        self._skipped_count += 1
        self._persist()

    def clear(self) -> None:
        """保持内容を空にし、永続化された状態も``ResumeStore``経由で削除する。"""
        self._features = []
        self._skipped_count = 0
        self._store.clear(self._key)

    def _persist(self) -> None:
        """現在の成功結果・スキップ件数の全体を``ResumeStore``へ保存する。"""
        self._store.save(
            self._key,
            {
                _PARTIAL_FEATURES_KEY: to_feature_collection_dict(self._features),
                _PARTIAL_SKIPPED_COUNT_KEY: self._skipped_count,
            },
        )


@dataclass(frozen=True)
class PrefectureRunResult:
    """1都道府県分の``run_prefecture``実行結果。"""

    prefecture: Prefecture
    """処理対象の都道府県。"""

    scraped_count: int
    """今回の都道府県処理で確定した詳細抽出成功件数(累計)。中断・再開をまたいだ場合は
    ``_PartialResultStore``から復元した分と今回新規に成功した分の合算(5.3)。"""

    skipped_count: int
    """今回の都道府県処理で確定したスキップ件数(累計)。中断・再開をまたいだ場合は
    ``_PartialResultStore``から復元した分と今回新規にスキップした分(detail段階、
    4.3, 5.3)に加え、一覧段階で座標を解釈できずスキップされた件数
    (``ListingResult.skipped_count``、3.4)も合算する。"""

    reactivated_count: int
    """削除状態から有効状態へ復帰した件数(8.3、``MergeResult.reactivated_count``)。"""

    newly_deleted_count: int
    """今回新たに削除状態へ遷移した件数(8.2、``MergeResult.newly_deleted_count``)。"""

    purged_count: int
    """保持期間超過により完全除去した件数(8.4、``MergeResult.purged_count``)。"""


def _collect_stubs(
    stubs: Sequence[StationStub],
    prefecture: Prefecture,
    *,
    fetcher: PageFetcher,
    resume: UrlResumeTracker,
    partial_store: _PartialResultStore | None = None,
) -> tuple[list[FacilityFeature], int]:
    """未処理のStationStubのみ詳細ページを取得・抽出し、成功結果とスキップ件数を返す。

    戻り値は(このループで新たに収集できたFacilityFeatureのリスト, このループで
    新たにスキップした件数)。resumeで既に処理済みと判定されたStationStubは
    詳細ページの取得すら行わずスキップする(重複処理の防止)。

    ``partial_store``を渡した場合、道の駅1件の処理(成功/失敗)が確定するたびに
    ``add_feature``/``add_skip``で``_PartialResultStore``へ逐次追記・永続化する
    (5.3、design.md flowchart I・J)。既定の``None``では永続化を行わず、
    タスク5.1時点の振る舞い(戻り値のみで結果を受け渡す)のまま動作する。
    """
    features: list[FacilityFeature] = []
    skipped_count = 0

    for stub in stubs:
        if resume.is_processed(stub.detail_url):
            # 6.1: 既に処理済み。失敗でも新規成功でもないため、成功結果・
            # スキップ件数のいずれにもカウントしない。
            continue

        try:
            fetched = fetcher.fetch_text(stub.detail_url)
            page = parse_html(fetched.text, fetched.url)
            properties = extract_station_properties(page, prefecture, stub.detail_url)
        except ScrapingEngineError as error:
            # 4.1-4.3: 個々の道の駅の抽出失敗は都道府県全体を中断させない。
            # 構造変化等は再試行しても解消しない可能性が高く、同一の
            # 中断・再開サイクル内での無駄な再試行を避けるため、成功時と
            # 同様にmark_processedを呼んだうえでスキップ件数を加算する。
            _logger.warning(
                "道の駅の詳細抽出に失敗したためスキップ: url=%s prefecture=%s error=%s",
                stub.detail_url,
                prefecture.name_ja,
                error,
            )
            skipped_count += 1
            if partial_store is not None:
                partial_store.add_skip()
            resume.mark_processed(stub.detail_url)
            continue

        feature = FacilityFeature(coordinate=stub.coordinate, properties=properties)
        features.append(feature)
        # 結果の永続化(add_feature/add_skip)を先に行い、その後に処理済み
        # フラグ(mark_processed)を立てる。逆順だと、両永続化の間で中断された
        # 場合に「処理済みだが結果未保存」となり、当該駅が今回サイクルの出力
        # から漏れる。この順序では再開時に同じ駅を再処理するだけで済む
        # (add_featureはsource_urlで冪等、run_prefecture側でも合算時に重複排除)。
        if partial_store is not None:
            partial_store.add_feature(feature)
        resume.mark_processed(stub.detail_url)

    return features, skipped_count


def run_prefecture(
    prefecture: Prefecture,
    *,
    fetcher: PageFetcher,
    resume: UrlResumeTracker,
    confirmed_at: datetime,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    index_path: Path | None = None,
    partial_result_store: ResumeStore | None = None,
) -> PrefectureRunResult | None:
    """1都道府県分のパイプラインを実行する。

    一覧取得(``fetch_station_stubs``)→ 中断前の部分結果を``_PartialResultStore``
    から復元 → ``_collect_stubs``で未処理分の詳細抽出(結果は逐次
    ``_PartialResultStore``へ永続化)→ ``read_geojson``で前回出力を読み戻し →
    ``merge_with_previous``で統合 → ``write_geojson``で出力 → ``index_store``の
    ``load_index``/``upsert_entry``/``save_index``で``index.json``を更新、
    正常完了時のみ``_PartialResultStore``を消去、という一連の処理を行う
    (design.md「都道府県単位の実行フロー」flowchart D〜O)。

    一覧取得失敗(HTTP取得失敗・要素の全欠落等の``ScrapingEngineError``全般)・
    前回GeoJSONの読み込み失敗・出力前検証違反(``GeoJsonValidationError``)の
    場合は``None``を返し、当該都道府県の処理のみを中断する(エラーはERRORログで
    報告する)。この場合``resume``は完了扱いにしない
    (``_collect_stubs``が処理した分の``mark_processed``はそのまま残ってよいが、
    都道府県全体を完了扱いにする追加操作は行わない)。同様に``_PartialResultStore``
    も消去しない(次回再開時に同じ部分結果から続行するため、5.3)。

    ``output_dir``・``index_path``・``partial_result_store``はテスト用に永続化先を
    差し替えるためのキーワード専用引数(既定はそれぞれ``geo-json/``・
    ``output_dir/index.json``・新規``ResumeStore()``、5.2/5.3)。
    """
    log_scrape_started(_logger, prefecture.name_ja)

    try:
        listing_result = fetch_station_stubs(fetcher, prefecture)
    except ScrapingEngineError as error:
        # 2.3, 5.2: 一覧段階の失敗(HTTP取得の最終失敗FetchFailedError・要素の
        # 全欠落ListingUnavailableError等)は、種別を問わず当該都道府県の処理のみを
        # 中断する。基底例外で捕捉しないと、一覧ページの一時的なHTTP失敗が
        # run_scopeのループごと巻き込んで他の都道府県の処理まで止めてしまう。
        # resumeは完了扱いにせず、次回再開時に再試行させる。
        _logger.error(
            "一覧取得に失敗したため都道府県処理を中断: prefecture=%s error=%s",
            prefecture.name_ja,
            error,
        )
        return None

    # 5.3: 都道府県処理開始時に、中断前の部分結果(scraped_features・
    # skipped_count)を_PartialResultStoreから復元する(flowchart D2)。
    partial_store = _PartialResultStore(prefecture, store=partial_result_store)
    restored_features = partial_store.features
    restored_skipped_count = partial_store.skipped_count

    new_features, new_skipped_count = _collect_stubs(
        listing_result.stubs,
        prefecture,
        fetcher=fetcher,
        resume=resume,
        partial_store=partial_store,
    )

    # 中断前後の成功結果・スキップ件数を合算する(6.1-6.3, 4.3)。さらに、
    # 一覧段階で座標(data-lat/data-lng)を解釈できずスキップされた件数
    # (listing_result.skipped_count、3.4)も都道府県単位の合計へ含める。
    # 一覧取得(fetch_station_stubsの呼び出し自体)はrun_prefectureが呼ばれる
    # たびに毎回行われ、_PartialResultStoreへは永続化されない値のため、
    # ここで一度だけ加算しても中断・再開をまたいだ二重カウントは発生しない。
    # 合算時はsource_urlで重複を排除し新結果を優先する(_PartialResultStoreへの
    # 永続化とmark_processedの間で中断された駅は、復元結果と今回結果の両方に
    # 現れうるため)。
    new_urls = {feature.properties.source_url for feature in new_features}
    features = [
        feature for feature in restored_features if feature.properties.source_url not in new_urls
    ] + new_features
    skipped_count = restored_skipped_count + new_skipped_count + listing_result.skipped_count

    filename = build_geojson_filename(prefecture, FacilityKind.MICHINOEKI)
    resolved_index_path = index_path if index_path is not None else output_dir / "index.json"

    try:
        previous_features = read_geojson(output_dir / filename)
    except (KeyError, TypeError, ValueError) as error:
        # 前回出力ファイルの破損(JSON構文不正・必須キー欠落・型不整合)は当該
        # 都道府県の処理のみを中断する。破損ファイルを空扱いで上書きすると削除
        # 状態・最終確認日時の履歴を失うため、自動再構築はせず運用者の対処に委ねる。
        _logger.error(
            "前回GeoJSONの読み込みに失敗したため都道府県処理を中断: prefecture=%s path=%s error=%r",
            prefecture.name_ja,
            output_dir / filename,
            error,
        )
        return None

    merge_result = merge_with_previous(
        previous_features,
        features,
        listing_result.listed_urls,
        confirmed_at,
    )

    try:
        write_geojson(merge_result.features, filename, output_dir=output_dir)
    except GeoJsonValidationError as error:
        # 5.2: 出力前検証違反は当該都道府県の処理のみを中断する。ファイルは
        # write_geojson自体が書き込まないため、ここでの追加対応は不要。resumeも
        # 完了扱いにせず、次回再開時に再試行させる。_PartialResultStoreも消去
        # しない(次回同じ部分結果から再開できるようにするため、5.3)。
        _logger.error(
            "出力前検証違反のため都道府県処理を中断: prefecture=%s error=%s",
            prefecture.name_ja,
            error,
        )
        return None

    index = index_store.load_index(resolved_index_path)
    index = index_store.upsert_entry(index, filename, confirmed_at)
    index_store.save_index(index, resolved_index_path)

    # 5.3: 出力まで正常完了した場合にのみ部分結果キャッシュを消去する(flowchart O)。
    partial_store.clear()

    log_scrape_finished(_logger, prefecture.name_ja, len(merge_result.features))
    _logger.info(
        "都道府県処理完了: prefecture=%s scraped=%d skipped=%d reactivated=%d newly_deleted=%d purged=%d",
        prefecture.name_ja,
        len(features),
        skipped_count,
        merge_result.reactivated_count,
        merge_result.newly_deleted_count,
        merge_result.purged_count,
    )

    return PrefectureRunResult(
        prefecture=prefecture,
        scraped_count=len(features),
        skipped_count=skipped_count,
        reactivated_count=merge_result.reactivated_count,
        newly_deleted_count=merge_result.newly_deleted_count,
        purged_count=merge_result.purged_count,
    )


def run_scope(
    spec: ScopeSpec,
    *,
    fetcher: PageFetcher | None = None,
    resume: UrlResumeTracker | None = None,
    confirmed_at: datetime | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    index_path: Path | None = None,
    partial_result_store: ResumeStore | None = None,
) -> list[PrefectureRunResult | None]:
    """resolve_scopeで得た都道府県を順に処理する。

    一覧取得・出力検証の失敗で中断した都道府県はNoneのまま結果列に含め、
    呼び出し側が失敗都道府県を判別できるようにする。全都道府県が
    Noneでない場合にのみresumeをclearする(design.md「都道府県単位の実行
    フロー」flowchart A〜C・P、6.3)。

    ``resolve_scope(spec)``は参照データのみに依存する純粋関数でHTTPリクエストを
    一切発生させないため、範囲指定が不正で``InvalidScopeError``を送出する場合も
    本関数はそのまま呼び出し側へ伝播し、以降のフェッチャー構築・都道府県処理は
    一切行わない(1.4)。

    1都道府県の一覧取得失敗・出力前検証違反(``run_prefecture``が``None``を
    返す場合)があっても、結果列に``None``を積んだうえで他の都道府県の処理を
    継続する(1.1-1.3、2.3、5.2)。

    ``fetcher``・``resume``・``confirmed_at``は省略時にそれぞれ既定値
    (``PageFetcher(load_scraping_config())``・``UrlResumeTracker("michinoeki")``・
    ``python_util.time_utility.now()``のJST時刻)で構築する。``confirmed_at``は
    本関数の呼び出し1回につき1つの値のみを取得し、対象都道府県すべてに同一値を
    渡す(1回の実行セッションとしての一貫したスナップショット、design.md
    「時刻」)。``UrlResumeTracker``のキーは範囲によらず単一の``"michinoeki"``
    とする(design.md runner Responsibilities & Constraints)。

    ``output_dir``・``index_path``・``partial_result_store``は各都道府県の
    ``run_prefecture``呼び出しへそのまま転送する、テスト用の永続化先差し替え
    引数(5.2/5.3と同じパターン)。
    """
    # 1.4: 範囲解決に失敗した場合、いかなるHTTPリクエストも発生しないよう、
    # フェッチャー等の構築より先にresolve_scopeを呼ぶ(InvalidScopeErrorは
    # そのまま呼び出し側へ伝播する)。
    prefectures = resolve_scope(spec)

    resolved_fetcher = fetcher if fetcher is not None else PageFetcher(load_scraping_config())
    resolved_resume = resume if resume is not None else UrlResumeTracker("michinoeki")
    resolved_confirmed_at = confirmed_at if confirmed_at is not None else time_utility.now()

    target = f"範囲全体(region={spec.region!r}, prefecture_code={spec.prefecture_code!r}, {len(prefectures)}都道府県)"
    log_scrape_started(_logger, target)

    results: list[PrefectureRunResult | None] = []
    for prefecture in prefectures:
        # 2.3, 5.2: 都道府県単位の失敗(Noneが返る)があってもループを止めず、
        # 他の対象都道府県の処理を継続する。
        result = run_prefecture(
            prefecture,
            fetcher=resolved_fetcher,
            resume=resolved_resume,
            confirmed_at=resolved_confirmed_at,
            output_dir=output_dir,
            index_path=index_path,
            partial_result_store=partial_result_store,
        )
        results.append(result)

    success_count = sum(1 for result in results if result is not None)
    failure_count = len(results) - success_count

    # 6.3: 指定範囲の全都道府県が(個別の道の駅スキップを許容しつつ)処理完了
    # した場合にのみresumeをclearする。1件でも失敗(None)があればクリアしない。
    if failure_count == 0:
        resolved_resume.clear()

    log_scrape_finished(_logger, target, success_count)
    _logger.info(
        "範囲全体の処理完了: prefectures=%d success=%d failure=%d",
        len(prefectures),
        success_count,
        failure_count,
    )

    return results
