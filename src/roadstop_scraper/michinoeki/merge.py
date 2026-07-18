"""前回出力のGeoJSONと今回のスクレイピング結果を統合し、削除状態を遷移させる(merge)。

対象サイトの一覧から一時的に確認できなくなっただけの道の駅を即座に削除せず、
削除状態(:class:`~roadstop_scraper.geojson.FacilityStatus.DELETED`)を明示した
うえで一定期間(既定365日)保持する。マージのキーは``FacilityProperties.source_url``
(詳細ページURL)を用いる。名称は表記揺れ・改称の可能性があるため識別子として
使わない(8.1〜8.5、design.md「削除状態の遷移(merge_with_previous)」参照)。

``listed_urls``(``listing.ListingResult.listed_urls``)は、今回の一覧取得で存在が
確認できた道の駅のURL集合であり、詳細抽出まで成功した``scraped_features``より
広い。前回存在し今回``scraped_features``に無い道の駅は、この``listed_urls``に
含まれるか否かで「一覧には実在するが今回は確認できなかっただけ(現状維持)」と
「一覧からも消失した(削除状態へ遷移)」を区別する。この区別が無いと、一時的な
抽出失敗が繰り返し起きた実在施設が誤って削除・完全除去されてしまう。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from roadstop_scraper.geojson import FacilityFeature, FacilityStatus

__all__ = ["MergeResult", "merge_with_previous"]


@dataclass(frozen=True)
class MergeResult:
    """マージ結果1回分。"""

    features: tuple[FacilityFeature, ...]
    """今回出力すべき施設の集合(順序は問わない)。"""

    reactivated_count: int
    """削除状態から有効状態へ復帰した施設数(8.3)。"""

    newly_deleted_count: int
    """今回新たに削除状態へ遷移した施設数(8.2)。"""

    purged_count: int
    """保持期間(``retention``)超過により結果から完全に除外した施設数(8.4)。"""


def merge_with_previous(
    previous_features: Sequence[FacilityFeature],
    scraped_features: Sequence[FacilityFeature],
    listed_urls: frozenset[str],
    confirmed_at: datetime,
    retention: timedelta = timedelta(days=365),
) -> MergeResult:
    """前回出力と今回スクレイピング結果をsource_urlで対応付けてマージする。

    listed_urlsは今回の一覧取得で存在が確認できた全道の駅のdetail_url集合
    (listing.ListingResult.listed_urls、詳細抽出の成否を問わない)。
    previous_featuresのうちscraped_featuresに含まれないものは、listed_urls
    に含まれるか否かで「今回確認できなかっただけ(現状維持)」と
    「一覧から消失した(削除状態へ遷移)」を区別する。
    """
    previous_by_url = {feature.properties.source_url: feature for feature in previous_features}
    scraped_urls = {feature.properties.source_url for feature in scraped_features}

    features: list[FacilityFeature] = []
    reactivated_count = 0
    newly_deleted_count = 0
    purged_count = 0

    # 1. 今回結果に含まれる道の駅: ACTIVE・last_confirmed_at=confirmed_atへ更新する(8.1)。
    #    前回DELETEDだったものは削除状態からの復帰としてカウントする(8.3)。
    for feature in scraped_features:
        url = feature.properties.source_url
        updated_properties = replace(
            feature.properties,
            status=FacilityStatus.ACTIVE,
            last_confirmed_at=confirmed_at,
        )
        features.append(replace(feature, properties=updated_properties))

        previous = previous_by_url.get(url)
        if previous is not None and FacilityStatus(previous.properties.status) is FacilityStatus.DELETED:
            reactivated_count += 1

    # 2. 前回存在し今回結果に無い道の駅: listed_urlsに含まれるか否かで分岐する。
    for url, previous in previous_by_url.items():
        if url in scraped_urls:
            continue

        if url in listed_urls:
            # 一覧には実在するが今回は抽出できなかった: 前回の状態のまま維持する
            # (今回確認できなかったことをもって削除方向へ倒してはならない)。
            features.append(previous)
            continue

        # 一覧からも消失している。
        if FacilityStatus(previous.properties.status) is not FacilityStatus.DELETED:
            # 前回ACTIVEだった: 削除状態へ遷移させる。last_confirmed_atは前回値を維持する(8.2)。
            deleted_properties = replace(previous.properties, status=FacilityStatus.DELETED)
            features.append(replace(previous, properties=deleted_properties))
            newly_deleted_count += 1
            continue

        # 前回既にDELETEDだった: 保持期間(retention)超過なら完全除去する(8.4)。
        last_confirmed_at = previous.properties.last_confirmed_at
        if last_confirmed_at is not None and confirmed_at - last_confirmed_at > retention:
            purged_count += 1
            continue

        # 保持期間内(last_confirmed_at不明な場合も防御的に保持継続扱い): 前回状態を維持する。
        features.append(previous)

    return MergeResult(
        features=tuple(features),
        reactivated_count=reactivated_count,
        newly_deleted_count=newly_deleted_count,
        purged_count=purged_count,
    )
