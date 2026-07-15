"""前回出力とのマージによる削除状態遷移(merge)の検証。

タスク4の観測可能な完了条件を検証する: 初回実行・消失による削除遷移・
再出現による復帰・保持期間超過による完全除去・保持期間内での維持、および
「一覧には実在するが今回抽出できなかった」施設が削除遷移せず前回状態を
維持することの各ケース(ACTIVE/DELETEDいずれの前回状態でも)を確認する
(8.1〜8.5、design.md「削除状態の遷移(merge_with_previous)」参照)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from roadstop_scraper.geojson import (
    Coordinate,
    FacilityFeature,
    FacilityKind,
    FacilityProperties,
    FacilityStatus,
)
from roadstop_scraper.michinoeki.merge import MergeResult, merge_with_previous

_CONFIRMED_AT = datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC)


def _build_feature(
    *,
    source_url: str,
    name: str = "道の駅 サンプル",
    status: FacilityStatus = FacilityStatus.ACTIVE,
    last_confirmed_at: datetime | None = None,
) -> FacilityFeature:
    # source_urlを区別のキーとして使う最小限のダミー値。
    return FacilityFeature(
        coordinate=Coordinate(longitude=141.0, latitude=43.0),
        properties=FacilityProperties(
            name=name,
            kind=FacilityKind.MICHINOEKI,
            pref_code="01",
            pref_name="北海道",
            source_url=source_url,
            status=status,
            last_confirmed_at=last_confirmed_at,
        ),
    )


def _find(result: MergeResult, source_url: str) -> FacilityFeature:
    matches = [f for f in result.features if f.properties.source_url == source_url]
    assert len(matches) == 1, f"{source_url} は features に1件だけ含まれるはず: {matches}"
    return matches[0]


class Test初回実行:
    def test_前回出力が無い場合全件がACTIVEとして確認日時付きで登録されカウントはすべて0(self):
        scraped = [
            _build_feature(source_url="https://example.com/a"),
            _build_feature(source_url="https://example.com/b"),
        ]

        result = merge_with_previous(
            previous_features=[],
            scraped_features=scraped,
            listed_urls=frozenset({"https://example.com/a", "https://example.com/b"}),
            confirmed_at=_CONFIRMED_AT,
        )

        assert len(result.features) == 2
        for feature in result.features:
            assert feature.properties.status is FacilityStatus.ACTIVE
            assert feature.properties.last_confirmed_at == _CONFIRMED_AT
        assert result.reactivated_count == 0
        assert result.newly_deleted_count == 0
        assert result.purged_count == 0


class Test一覧から消失した施設の削除遷移:
    def test_listed_urlsにも含まれず消失したACTIVE施設はDELETEDへ遷移し確認日時は前回値のまま(self):
        previous_confirmed_at = _CONFIRMED_AT - timedelta(days=10)
        previous = [
            _build_feature(
                source_url="https://example.com/gone",
                status=FacilityStatus.ACTIVE,
                last_confirmed_at=previous_confirmed_at,
            ),
        ]

        result = merge_with_previous(
            previous_features=previous,
            scraped_features=[],
            listed_urls=frozenset(),
            confirmed_at=_CONFIRMED_AT,
        )

        feature = _find(result, "https://example.com/gone")
        assert feature.properties.status is FacilityStatus.DELETED
        assert feature.properties.last_confirmed_at == previous_confirmed_at
        assert result.newly_deleted_count == 1
        assert result.reactivated_count == 0
        assert result.purged_count == 0


class Test削除状態からの復帰:
    def test_DELETEDだった施設が今回再出現するとACTIVEへ戻り確認日時が更新されreactivated_countが増加する(self):
        previous_confirmed_at = _CONFIRMED_AT - timedelta(days=30)
        previous = [
            _build_feature(
                source_url="https://example.com/back",
                status=FacilityStatus.DELETED,
                last_confirmed_at=previous_confirmed_at,
            ),
        ]
        scraped = [_build_feature(source_url="https://example.com/back")]

        result = merge_with_previous(
            previous_features=previous,
            scraped_features=scraped,
            listed_urls=frozenset({"https://example.com/back"}),
            confirmed_at=_CONFIRMED_AT,
        )

        feature = _find(result, "https://example.com/back")
        assert feature.properties.status is FacilityStatus.ACTIVE
        assert feature.properties.last_confirmed_at == _CONFIRMED_AT
        assert result.reactivated_count == 1
        assert result.newly_deleted_count == 0
        assert result.purged_count == 0

    def test_初出の施設や前回ACTIVEだった施設はreactivated_countに計上しない(self):
        previous = [
            _build_feature(
                source_url="https://example.com/already-active",
                status=FacilityStatus.ACTIVE,
                last_confirmed_at=_CONFIRMED_AT - timedelta(days=1),
            ),
        ]
        scraped = [
            _build_feature(source_url="https://example.com/already-active"),
            _build_feature(source_url="https://example.com/brand-new"),
        ]

        result = merge_with_previous(
            previous_features=previous,
            scraped_features=scraped,
            listed_urls=frozenset({"https://example.com/already-active", "https://example.com/brand-new"}),
            confirmed_at=_CONFIRMED_AT,
        )

        assert result.reactivated_count == 0


class Test保持期間超過による完全除去:
    def test_ちょうど365日はまだ除外されない(self):
        previous_confirmed_at = _CONFIRMED_AT - timedelta(days=365)
        previous = [
            _build_feature(
                source_url="https://example.com/exactly-boundary",
                status=FacilityStatus.DELETED,
                last_confirmed_at=previous_confirmed_at,
            ),
        ]

        result = merge_with_previous(
            previous_features=previous,
            scraped_features=[],
            listed_urls=frozenset(),
            confirmed_at=_CONFIRMED_AT,
        )

        feature = _find(result, "https://example.com/exactly-boundary")
        assert feature.properties.status is FacilityStatus.DELETED
        assert feature.properties.last_confirmed_at == previous_confirmed_at
        assert result.purged_count == 0

    def test_365日と1日経過した施設はfeaturesから完全に除外されpurged_countが増加する(self):
        previous_confirmed_at = _CONFIRMED_AT - timedelta(days=366)
        previous = [
            _build_feature(
                source_url="https://example.com/over-retention",
                status=FacilityStatus.DELETED,
                last_confirmed_at=previous_confirmed_at,
            ),
        ]

        result = merge_with_previous(
            previous_features=previous,
            scraped_features=[],
            listed_urls=frozenset(),
            confirmed_at=_CONFIRMED_AT,
        )

        assert all(f.properties.source_url != "https://example.com/over-retention" for f in result.features)
        assert result.purged_count == 1
        assert result.newly_deleted_count == 0
        assert result.reactivated_count == 0


class Test保持期間内での維持:
    def test_DELETEDかつ保持期間未満の施設は変更されずfeaturesに維持される(self):
        previous_confirmed_at = _CONFIRMED_AT - timedelta(days=100)
        previous = [
            _build_feature(
                source_url="https://example.com/still-within-retention",
                status=FacilityStatus.DELETED,
                last_confirmed_at=previous_confirmed_at,
            ),
        ]

        result = merge_with_previous(
            previous_features=previous,
            scraped_features=[],
            listed_urls=frozenset(),
            confirmed_at=_CONFIRMED_AT,
        )

        feature = _find(result, "https://example.com/still-within-retention")
        assert feature.properties.status is FacilityStatus.DELETED
        assert feature.properties.last_confirmed_at == previous_confirmed_at
        assert result.purged_count == 0
        assert result.newly_deleted_count == 0


class Test一覧には実在するが今回抽出できなかった施設は前回状態を維持:
    def test_前回ACTIVEだった施設はstatusもlast_confirmed_atも変化しない(self):
        previous_confirmed_at = _CONFIRMED_AT - timedelta(days=5)
        previous = [
            _build_feature(
                source_url="https://example.com/listed-but-not-scraped-active",
                status=FacilityStatus.ACTIVE,
                last_confirmed_at=previous_confirmed_at,
            ),
        ]

        result = merge_with_previous(
            previous_features=previous,
            scraped_features=[],
            listed_urls=frozenset({"https://example.com/listed-but-not-scraped-active"}),
            confirmed_at=_CONFIRMED_AT,
        )

        feature = _find(result, "https://example.com/listed-but-not-scraped-active")
        assert feature.properties.status is FacilityStatus.ACTIVE
        assert feature.properties.last_confirmed_at == previous_confirmed_at
        assert result.newly_deleted_count == 0
        assert result.reactivated_count == 0
        assert result.purged_count == 0

    def test_前回DELETEDだった施設はstatusもlast_confirmed_atも変化せず完全除去もされない(self):
        # 保持期間を超過していても、listed_urlsに含まれる限りは除去判定の対象外とする。
        previous_confirmed_at = _CONFIRMED_AT - timedelta(days=400)
        previous = [
            _build_feature(
                source_url="https://example.com/listed-but-not-scraped-deleted",
                status=FacilityStatus.DELETED,
                last_confirmed_at=previous_confirmed_at,
            ),
        ]

        result = merge_with_previous(
            previous_features=previous,
            scraped_features=[],
            listed_urls=frozenset({"https://example.com/listed-but-not-scraped-deleted"}),
            confirmed_at=_CONFIRMED_AT,
        )

        feature = _find(result, "https://example.com/listed-but-not-scraped-deleted")
        assert feature.properties.status is FacilityStatus.DELETED
        assert feature.properties.last_confirmed_at == previous_confirmed_at
        assert result.newly_deleted_count == 0
        assert result.purged_count == 0
        assert result.reactivated_count == 0
