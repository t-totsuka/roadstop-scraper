"""都道府県単位・範囲単位のオーケストレーション(runner)。

本モジュールはタスク5.1〜5.4にわたって段階的に構築される。タスク5.1時点では、
一覧取得済みの``StationStub``列を基に未処理の道の駅のみ詳細抽出し、成功結果と
スキップ件数を蓄積する収集ループ(design.md「都道府県単位の実行フロー」
flowchart F〜J)のみを実装する。公開APIとしての``run_prefecture``/``run_scope``
はマージ・出力・部分結果キャッシュを扱う後続タスク(5.2〜5.4)で追加される。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from roadstop_scraper.common.logging_setup import get_logger
from roadstop_scraper.geojson import FacilityFeature, Prefecture
from roadstop_scraper.michinoeki.detail import extract_station_properties
from roadstop_scraper.scraping import PageFetcher, ScrapingEngineError, UrlResumeTracker, parse_html

if TYPE_CHECKING:
    from collections.abc import Sequence

    from roadstop_scraper.michinoeki.listing import StationStub

__all__: list[str] = []

_logger = get_logger(__name__)


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
