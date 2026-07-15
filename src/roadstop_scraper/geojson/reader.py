"""前回出力済みGeoJSONの読み戻し。

差分反映(merge)は今回スクレイピング結果と前回出力を突き合わせて削除状態・
最終確認日時を更新するため、前回出力されたGeoJSONファイルを施設情報の列へ
読み戻す経路が必要になる。本モジュールはその読み戻し専用の入口であり、
書き込み時の変換(:func:`~roadstop_scraper.geojson.models.to_feature_collection_dict`)
の逆方向を :func:`~roadstop_scraper.geojson.models.from_feature_collection_dict`
に委譲する。
"""

from __future__ import annotations

import json
from pathlib import Path

from roadstop_scraper.geojson.models import FacilityFeature, from_feature_collection_dict

__all__ = ["read_geojson"]


def read_geojson(path: Path) -> list[FacilityFeature]:
    """``path`` のGeoJSONファイルを読み込み、施設情報の列へ変換して返す。

    ``path`` が存在しない場合は空リストを返す(初回実行・前回ファイル未存在の
    ケースに対応。``common.index_store.load_index`` が存在しないファイルに
    対して空の ``IndexData`` を返す既存パターンと同じ方針)。
    """
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    return from_feature_collection_dict(data)
