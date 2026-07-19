"""サイト単位の収集ループと部分結果の逐次永続化(雛形)。

1サイト分の一覧→詳細→座標解決→Feature化の収集ループ(``collect_site``)
と、実行横断の部分結果キャッシュ(``SapaPartialStore``)を提供するモジュール
(design.md「sapa.collector」節参照)。``collect_site``/``SiteCollectResult``/
``SiteListingError``の実装はタスク4.2で行う。
"""

from __future__ import annotations

from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import (
    FacilityFeature,
    from_feature_collection_dict,
    to_feature_collection_dict,
)

__all__ = ["SapaPartialStore"]

_PARTIAL_STORE_KEY = "sapa-partial"
_PARTIAL_FEATURES_KEY = "features"
_PARTIAL_SKIPPED_COUNTS_KEY = "skipped_counts"
_PARTIAL_GEOCODED_COUNTS_KEY = "geocoded_counts"
_UNKNOWN_PREFECTURE_BUCKET = "unknown"
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
