"""検証ゲート付きGeoJSON出力。

スキーマ違反データが ``geo-json/`` 配下へ永続化されないよう、書き込み前に必ず
:func:`~roadstop_scraper.geojson.validation.validate_features` と
:func:`~roadstop_scraper.geojson.validation.validate_filename` を実行する。違反が
1件でもあれば全違反を保持した :class:`GeoJsonValidationError` を送出し、ファイルを
書き込まない(5.5)。検証合格時のみ、共通基盤のアトミック書き込みで
FeatureCollectionをJSONとして出力する。

本モジュールは未検証データの書き込み経路を存在させない唯一の出力ゲートウェイで
あり、05/06スクレイパはこの経路のみを通じて ``geo-json/`` へ出力する。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from roadstop_scraper.common._atomic_io import write_text_atomic
from roadstop_scraper.common.logging_setup import get_logger
from roadstop_scraper.geojson.models import (
    FacilityFeature,
    to_feature_collection_dict,
)
from roadstop_scraper.geojson.naming import DEFAULT_OUTPUT_DIR
from roadstop_scraper.geojson.validation import (
    ValidationIssue,
    validate_features,
    validate_filename,
)

__all__ = [
    "GeoJsonValidationError",
    "write_geojson",
]

_logger = get_logger(__name__)

# 例外メッセージ・ログに含める違反の要約件数。全違反はissuesに保持されるため、
# ここでは利用者が概況を把握できる先頭数件だけを文字列化する。
_ISSUE_SUMMARY_LIMIT = 3


class GeoJsonValidationError(ValueError):
    """出力前検証で違反が検出された場合に送出される。

    :attr:`issues` に全違反を保持し、メッセージには件数と先頭数件の要約を含める
    (利用者が一度の実行で全問題を把握できるようにする)。
    """

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)
        super().__init__(
            f"出力前検証で{len(self.issues)}件の違反が見つかりました: "
            f"{_summarize_issues(self.issues)}"
        )


def _summarize_issues(issues: Sequence[ValidationIssue]) -> str:
    # 先頭数件を "location: message" 形式で連結し、超過分は省略記号で示す。
    head = "; ".join(
        f"{issue.location}: {issue.message}" for issue in issues[:_ISSUE_SUMMARY_LIMIT]
    )
    return f"{head} ..." if len(issues) > _ISSUE_SUMMARY_LIMIT else head


def write_geojson(
    features: Sequence[FacilityFeature],
    filename: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    """検証合格時のみFeatureCollectionをJSONとして書き込み、出力先パスを返す。

    書き込み前にファイル名(5.4)とFeature列(5.1〜5.3)を検証し、違反が1件でも
    あれば全違反を保持した :class:`GeoJsonValidationError` を送出してファイルを
    書き込まない(5.5)。検証合格時のみ ``output_dir/filename`` へアトミックに
    書き込み、そのパスを返す(5.6)。``output_dir`` は存在しなくてよく、書き込み前に
    作成する。同一入力での再実行は同一内容の上書きとなり冪等。
    """
    # ファイル名とFeatureの違反を1回の実行で網羅的に集約する(最初の違反で打ち切らない)
    issues = [*validate_filename(filename), *validate_features(features)]
    if issues:
        _logger.warning(
            "GeoJSON出力前検証で違反を検出: filename=%s issues=%d 要約=%s",
            filename,
            len(issues),
            _summarize_issues(issues),
        )
        raise GeoJsonValidationError(issues)

    output_path = output_dir / filename
    content = (
        json.dumps(
            to_feature_collection_dict(features), ensure_ascii=False, indent=2
        )
        + "\n"
    )
    # write_text_atomicは親ディレクトリの存在を前提とするため、書き込み前に作成する。
    # 検証で中断した場合はここに到達しないため、違反時に出力先が作られることはない。
    output_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output_path, content)
    _logger.info(
        "GeoJSONを出力: path=%s features=%d", output_path, len(features)
    )
    return output_path
