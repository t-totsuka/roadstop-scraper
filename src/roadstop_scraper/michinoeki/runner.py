"""都道府県単位・範囲単位のオーケストレーション(runner)。

本モジュールはタスク5.1〜5.4にわたって段階的に構築される。タスク5.1で、
一覧取得済みの``StationStub``列を基に未処理の道の駅のみ詳細抽出し、成功結果と
スキップ件数を蓄積する収集ループ(design.md「都道府県単位の実行フロー」
flowchart F〜J)を実装した。タスク5.2では、この収集ループへ一覧取得・前回
GeoJSONとのマージ・出力・``index.json``更新を統合した公開関数``run_prefecture``
を追加する(flowchart D〜O)。本タスク時点では中断・再開をまたいだ都道府県単位
の部分結果キャッシュ(``_PartialResultStore``)は扱わず、1回の実行で最初から
最後まで通す前提とする(5.3で追記予定)。範囲全体のオーケストレーション
(``run_scope``)は5.4で追加される。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from roadstop_scraper.common import index_store
from roadstop_scraper.common.logging_setup import get_logger, log_scrape_finished, log_scrape_started
from roadstop_scraper.geojson import (
    DEFAULT_OUTPUT_DIR,
    FacilityFeature,
    FacilityKind,
    GeoJsonValidationError,
    Prefecture,
    build_geojson_filename,
    read_geojson,
    write_geojson,
)
from roadstop_scraper.michinoeki.detail import extract_station_properties
from roadstop_scraper.michinoeki.listing import ListingUnavailableError, fetch_station_stubs
from roadstop_scraper.michinoeki.merge import merge_with_previous
from roadstop_scraper.scraping import PageFetcher, ScrapingEngineError, UrlResumeTracker, parse_html

if TYPE_CHECKING:
    from collections.abc import Sequence

    from roadstop_scraper.michinoeki.listing import StationStub

__all__ = ["PrefectureRunResult", "run_prefecture"]

_logger = get_logger(__name__)


@dataclass(frozen=True)
class PrefectureRunResult:
    """1都道府県分の``run_prefecture``実行結果。"""

    prefecture: Prefecture
    """処理対象の都道府県。"""

    scraped_count: int
    """今回新たに詳細抽出に成功した件数(``_collect_stubs``の戻り値をそのまま用いる)。"""

    skipped_count: int
    """今回新たにスキップした件数(``_collect_stubs``の戻り値をそのまま用いる)。"""

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
) -> tuple[list[FacilityFeature], int]:
    """未処理のStationStubのみ詳細ページを取得・抽出し、成功結果とスキップ件数を返す。

    戻り値は(このループで新たに収集できたFacilityFeatureのリスト, このループで
    新たにスキップした件数)。resumeで既に処理済みと判定されたStationStubは
    詳細ページの取得すら行わずスキップする(重複処理の防止)。
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
            resume.mark_processed(stub.detail_url)
            continue

        features.append(FacilityFeature(coordinate=stub.coordinate, properties=properties))
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
) -> PrefectureRunResult | None:
    """1都道府県分のパイプラインを実行する。

    一覧取得(``fetch_station_stubs``)→ ``_collect_stubs``で未処理分の詳細抽出 →
    ``read_geojson``で前回出力を読み戻し → ``merge_with_previous``で統合 →
    ``write_geojson``で出力 → ``index_store``の``load_index``/``upsert_entry``/
    ``save_index``で``index.json``を更新、という一連の処理を行う(design.md
    「都道府県単位の実行フロー」flowchart D〜O)。

    一覧取得失敗(``ListingUnavailableError``)・出力前検証違反
    (``GeoJsonValidationError``)の場合は``None``を返し、当該都道府県の処理のみを
    中断する(エラーはERRORログで報告する)。この場合``resume``は完了扱いにしない
    (``_collect_stubs``が処理した分の``mark_processed``はそのまま残ってよいが、
    都道府県全体を完了扱いにする追加操作は行わない)。

    ``output_dir``・``index_path``はテスト用に出力先を差し替えるためのキーワード
    専用引数(既定はそれぞれ``geo-json/``・``output_dir/index.json``)。
    """
    log_scrape_started(_logger, prefecture.name_ja)

    try:
        listing_result = fetch_station_stubs(fetcher, prefecture)
    except ListingUnavailableError as error:
        # 2.3, 5.2: 一覧取得失敗は当該都道府県の処理のみを中断する。resumeは
        # 完了扱いにせず、次回再開時に再試行させる。
        _logger.error(
            "一覧取得に失敗したため都道府県処理を中断: prefecture=%s error=%s",
            prefecture.name_ja,
            error,
        )
        return None

    features, skipped_count = _collect_stubs(listing_result.stubs, prefecture, fetcher=fetcher, resume=resume)

    filename = build_geojson_filename(prefecture, FacilityKind.MICHINOEKI)
    resolved_index_path = index_path if index_path is not None else output_dir / "index.json"

    previous_features = read_geojson(output_dir / filename)
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
        # 完了扱いにせず、次回再開時に再試行させる。
        _logger.error(
            "出力前検証違反のため都道府県処理を中断: prefecture=%s error=%s",
            prefecture.name_ja,
            error,
        )
        return None

    index = index_store.load_index(resolved_index_path)
    index = index_store.upsert_entry(index, filename, confirmed_at)
    index_store.save_index(index, resolved_index_path)

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
