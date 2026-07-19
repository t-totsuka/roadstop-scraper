"""都道府県グルーピングとマージ・出力・index更新(design.md「sapa.runner」節)。

本モジュールはタスク5.1で、成功サイトの収集結果(``SiteCollectResult``)を
都道府県ごとにグルーピングし、前回出力の読み戻し→前回施設のサイト帰属分割
(失敗サイト帰属分は削除判定から除外し現状維持で出力へ合流)→
``merge_with_previous``による削除状態遷移→検証付きGeoJSON出力→``index.json``
更新を都道府県ごとに実行する処理を実装する(design.md flowchart K〜N、
research.md「サイト単位の一覧取得失敗は『当該サイトの前回データ現状維持』で
隔離する」)。

範囲解決(``resolve_scope``)・サイト横断収集(``collect_site``)・レジューム/
部分結果クリア・集計ログの全体オーケストレーション(``run_scope``)はタスク
5.2の責務であり、本モジュールでは実装しない。本タスクが公開する
``run_prefecture``(1都道府県分の処理)・``run_prefectures``(複数
``SiteCollectResult``からの都道府県グルーピング+全対象都道府県への
``run_prefecture``適用)は、5.2の``run_scope``が呼び出す部品として設計する。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from roadstop_scraper.common import index_store
from roadstop_scraper.common.logging_setup import get_logger
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
from roadstop_scraper.pipeline import merge_with_previous

if TYPE_CHECKING:
    from roadstop_scraper.sapa.collector import SiteCollectResult
    from roadstop_scraper.sapa.sites import SapaSite

__all__ = ["SapaPrefectureResult", "run_prefecture", "run_prefectures"]

_logger = get_logger(__name__)


@dataclass(frozen=True)
class SapaPrefectureResult:
    """1都道府県分の``run_prefecture``実行結果(design.md「sapa.runner」Batch/Job Contract)。

    ``skipped_count``・``geocoded_count``は本タスクの``run_prefecture``自体は
    計算せず、呼び出し側(``run_prefectures``、または将来の``run_scope``)が
    ``SiteCollectResult.skipped_counts``/``geocoded_counts``(都道府県コード別
    マップ)から当該都道府県分を集計して渡す値をそのまま保持する
    (このモジュールのCONCERNS参照)。
    """

    prefecture: Prefecture
    """処理対象の都道府県。"""

    scraped_count: int
    """今回この都道府県向けに集約された新規スクレイピング結果の件数
    (成功サイトの``SiteCollectResult.features``をpref_codeで集約した件数)。"""

    skipped_count: int
    """今回この都道府県向けに集計されたスキップ件数(呼び出し側が集計して渡す値)。"""

    geocoded_count: int
    """今回この都道府県向けに集計されたジオコーディング補完件数(呼び出し側が集計して渡す値)。"""

    reactivated_count: int
    """削除状態から有効状態へ復帰した件数(9.3、``MergeResult.reactivated_count``)。"""

    newly_deleted_count: int
    """今回新たに削除状態へ遷移した件数(9.2、``MergeResult.newly_deleted_count``)。"""

    purged_count: int
    """保持期間超過により完全除去した件数(9.4、``MergeResult.purged_count``)。"""


def _split_previous_by_site_attribution(
    previous_features: Sequence[FacilityFeature],
    failed_site_keys: Set[str],
    all_sites: Sequence[SapaSite],
) -> tuple[list[FacilityFeature], list[FacilityFeature]]:
    """前回施設を``owns_url``でサイト帰属判定し、失敗サイト帰属分と、それ以外
    (成功サイト帰属+どのサイトにも帰属しない孤児施設)に分割する。

    research.md「サイト単位の一覧取得失敗は現状維持で隔離する」のとおり、
    失敗サイト帰属分は``merge_with_previous``の入力から除外し、そのまま
    最終出力へ現状維持で合流させる(戻り値の1要素目)。孤児施設(どの
    ``SapaSite.owns_url``にも一致しない)はdesign.mdの明示のとおり通常の
    削除判定に含める(戻り値の2要素目)。
    """
    carried_through_unchanged: list[FacilityFeature] = []
    subject_to_merge: list[FacilityFeature] = []

    for feature in previous_features:
        url = feature.properties.source_url
        owner = next((site for site in all_sites if site.owns_url(url)), None)
        if owner is not None and owner.key in failed_site_keys:
            carried_through_unchanged.append(feature)
        else:
            subject_to_merge.append(feature)

    return carried_through_unchanged, subject_to_merge


def run_prefecture(
    prefecture: Prefecture,
    features: Sequence[FacilityFeature],
    listed_urls: frozenset[str],
    failed_site_keys: Set[str],
    all_sites: Sequence[SapaSite],
    confirmed_at: datetime,
    *,
    skipped_count: int = 0,
    geocoded_count: int = 0,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    index_path: Path | None = None,
) -> SapaPrefectureResult | None:
    """1都道府県分のマージ・出力・index更新パイプラインを実行する。

    前回GeoJSON読み戻し(``read_geojson``)→前回施設のサイト帰属分割
    (``_split_previous_by_site_attribution``)→成功サイト帰属+孤児施設分を
    ``merge_with_previous``でマージ→失敗サイト帰属分を現状維持のまま合流→
    ``write_geojson``で出力→``index_store``の``load_index``/``upsert_entry``/
    ``save_index``で``index.json``を更新、という一連の処理を行う
    (design.md「都道府県単位の実行フロー」flowchart K〜N)。

    前回GeoJSONの読み込み失敗(JSON構文不正・必須キー欠落・型不整合)・
    出力前検証違反(``GeoJsonValidationError``)の場合は``None``を返し、当該
    都道府県の処理のみを中断する(エラーはERRORログで報告する)。この場合
    ``index.json``は更新しない(design.md Error Handling表「都道府県単位」行、
    6.2)。

    ``features``・``listed_urls``は、この都道府県向けに集約された成功サイトの
    寄与分(呼び出し側の``run_prefectures``が集約する。単一サイトの寄与のみを
    渡す場合も、複数サイトの和集合を渡す場合もどちらでも動作する)。
    ``failed_site_keys``は今回の実行で一覧取得に失敗したサイトの識別子集合、
    ``all_sites``は前回施設のサイト帰属判定(``owns_url``)に必要な全サイト
    (成功・失敗を問わない)の列。

    ``output_dir``・``index_path``はテスト用に永続化先を差し替えるための
    キーワード専用引数(既定はそれぞれ``geo-json/``・``output_dir/index.json``、
    michinoeki.runner.run_prefectureと同じパターン)。
    """
    filename = build_geojson_filename(prefecture, FacilityKind.SAPA)
    resolved_index_path = index_path if index_path is not None else output_dir / "index.json"

    try:
        previous_features = read_geojson(output_dir / filename)
    except (KeyError, TypeError, ValueError) as error:
        # 前回出力ファイルの破損は当該都道府県の処理のみを中断する
        # (michinoeki.runner.run_prefectureと同じ判断: 破損ファイルを空扱いで
        # 上書きすると削除状態・最終確認日時の履歴を失うため、自動再構築はせず
        # 運用者の対処に委ねる)。
        _logger.error(
            "前回GeoJSONの読み込みに失敗したため都道府県処理を中断: prefecture=%s path=%s error=%r",
            prefecture.name_ja,
            output_dir / filename,
            error,
        )
        return None

    carried_through_unchanged, mergeable_previous = _split_previous_by_site_attribution(
        previous_features, failed_site_keys, all_sites
    )

    merge_result = merge_with_previous(
        mergeable_previous,
        features,
        listed_urls,
        confirmed_at,
    )

    final_features = [*merge_result.features, *carried_through_unchanged]

    try:
        write_geojson(final_features, filename, output_dir=output_dir)
    except GeoJsonValidationError as error:
        # 6.2: 出力前検証違反は当該都道府県の処理のみを中断する。write_geojson
        # 自体が検証違反時にファイルを書き込まないため、ここでの追加対応は不要。
        _logger.error(
            "出力前検証違反のため都道府県処理を中断: prefecture=%s error=%s",
            prefecture.name_ja,
            error,
        )
        return None

    index = index_store.load_index(resolved_index_path)
    index = index_store.upsert_entry(index, filename, confirmed_at)
    index_store.save_index(index, resolved_index_path)

    _logger.info(
        "都道府県処理完了: prefecture=%s scraped=%d skipped=%d geocoded=%d reactivated=%d newly_deleted=%d purged=%d",
        prefecture.name_ja,
        len(features),
        skipped_count,
        geocoded_count,
        merge_result.reactivated_count,
        merge_result.newly_deleted_count,
        merge_result.purged_count,
    )

    return SapaPrefectureResult(
        prefecture=prefecture,
        scraped_count=len(features),
        skipped_count=skipped_count,
        geocoded_count=geocoded_count,
        reactivated_count=merge_result.reactivated_count,
        newly_deleted_count=merge_result.newly_deleted_count,
        purged_count=merge_result.purged_count,
    )


def _group_features_by_prefecture(
    site_results: Sequence[SiteCollectResult],
) -> dict[str, list[FacilityFeature]]:
    """成功サイトの``SiteCollectResult.features``を``pref_code``で都道府県別に集約する。

    ``pref_code``はタスク4.2の``collect_site``が範囲内都道府県の確定値として
    既に設定済みの``FacilityProperties``フィールドであり、ここでの再導出は
    不要(design.md「sapa.runner」Responsibilities)。
    """
    grouped: dict[str, list[FacilityFeature]] = {}
    for result in site_results:
        for feature in result.features:
            grouped.setdefault(feature.properties.pref_code, []).append(feature)
    return grouped


def _aggregate_counts_by_prefecture(
    counts_by_site: Sequence[Mapping[str, int]],
) -> dict[str, int]:
    """複数サイトの都道府県コード別件数マップを都道府県コードごとに合算する。

    ``"unknown"``バケット(都道府県を特定できなかった件数)は、特定の都道府県
    に帰属させられないためここでの集計対象から除外する(このモジュールの
    CONCERNS参照。呼び出し側が実行全体の集計ログで別途扱う想定)。
    """
    aggregated: dict[str, int] = {}
    for counts in counts_by_site:
        for pref_code, count in counts.items():
            if pref_code == "unknown":
                continue
            aggregated[pref_code] = aggregated.get(pref_code, 0) + count
    return aggregated


def run_prefectures(
    scope_prefectures: Sequence[Prefecture],
    site_results: Sequence[SiteCollectResult],
    failed_site_keys: Set[str],
    all_sites: Sequence[SapaSite],
    confirmed_at: datetime,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    index_path: Path | None = None,
) -> list[SapaPrefectureResult | None]:
    """複数サイトの成功収集結果を都道府県ごとにグルーピングし、範囲内の全都道府県を処理する。

    ``site_results``(成功サイトのみの``SiteCollectResult``列。一覧取得に
    失敗したサイトは``collect_site``が例外を送出するため、ここには現れない
    ――``failed_site_keys``で別途識別子を受け取る)から:

    - 各サイトの``features``を``pref_code``で都道府県別バケットへ振り分ける
      (``_group_features_by_prefecture``)
    - ``listed_urls``は都道府県別に分割せず、全成功サイトの和集合を単一の値
      として全都道府県の``run_prefecture``呼び出しへ渡す(design.md
      「listed_urlsは成功サイトの和集合」。このモジュールのCONCERNS参照)
    - ``skipped_counts``/``geocoded_counts``(都道府県コード別マップ)も同様に
      全サイトを都道府県コードごとに合算し、対応する都道府県の
      ``run_prefecture``呼び出しへ渡す

    ``scope_prefectures``に含まれる全都道府県を処理対象とする(design.md
    「範囲内都道府県のファイルのみを読み書きする」9.5。今回の新規収集が0件の
    都道府県であっても、前回出力済みの施設が削除状態へ正しく遷移できるよう
    処理対象に含める必要があるため、"今回データがある都道府県のみ"へは絞り
    込まない)。
    """
    features_by_pref = _group_features_by_prefecture(site_results)
    listed_urls_union: frozenset[str] = frozenset().union(*(result.listed_urls for result in site_results))
    skipped_by_pref = _aggregate_counts_by_prefecture([result.skipped_counts for result in site_results])
    geocoded_by_pref = _aggregate_counts_by_prefecture([result.geocoded_counts for result in site_results])

    results: list[SapaPrefectureResult | None] = []
    for prefecture in scope_prefectures:
        result = run_prefecture(
            prefecture,
            features_by_pref.get(prefecture.code, []),
            listed_urls_union,
            failed_site_keys,
            all_sites,
            confirmed_at,
            skipped_count=skipped_by_pref.get(prefecture.code, 0),
            geocoded_count=geocoded_by_pref.get(prefecture.code, 0),
            output_dir=output_dir,
            index_path=index_path,
        )
        results.append(result)

    return results
