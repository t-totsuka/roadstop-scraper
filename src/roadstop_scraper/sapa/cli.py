"""実行エントリポイント(コマンドライン引数の解釈と`runner.run_scope`の起動)。

design.md「エントリポイント #cli」: 運用者からの範囲指定引数(`--region`・
`--prefecture-code`)を`argparse`で受け付ける。両引数の値そのものの妥当性
(地方区分・都道府県コードが実在するか、両方同時指定でないか)は`argparse`の
`choices=`等では検証しない。検証を`scope.resolve_scope`(`ScopeSpec`から
`InvalidScopeError`を送出する唯一の正)に一本化することで、`REGIONS`等の
参照データが変更された際の追従漏れやエラーメッセージの分散を防ぐ
(Requirements 1.1-1.4。michinoeki.cliと同形式)。
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from roadstop_scraper.pipeline import InvalidScopeError, ScopeSpec, resolve_scope
from roadstop_scraper.sapa.runner import run_scope

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    """コマンドライン引数パーサを構築する。

    `--region`・`--prefecture-code`は値の制約なしの任意の文字列引数として
    受け付ける(`choices=`等によるargparse自身での検証は行わない)。実在する
    値かどうか・両方同時指定でないかは、`main`内で`scope.resolve_scope`が
    検証する。
    """
    parser = argparse.ArgumentParser(
        prog="sapa-scrape",
        description="全国の高速道路SA/PAの位置情報・名称・付加情報をスクレイピングし、都道府県単位のGeoJSONへ出力する。",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="対象とする地方区分(例: kanto)。省略時は--prefecture-codeとあわせて全国が対象。",
    )
    parser.add_argument(
        "--prefecture-code",
        default=None,
        help="対象とする都道府県コード(例: 13)。省略時は--regionとあわせて全国が対象。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """コマンドライン引数を解釈しrun_scopeを実行する。

    全サイトの一覧取得・範囲内全都道府県の出力が成功した場合のみ0を返す。範囲
    指定エラー、またはサイトもしくは都道府県の処理が1件でも失敗
    (``run_scope``の結果の``failed_site_keys``・``failed_prefecture_codes``の
    いずれかが空でない)した場合は非ゼロを返し、cron等の運用監視が終了コードで
    失敗を検知できるようにする(1.1-1.4)。
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    spec = ScopeSpec(region=args.region, prefecture_code=args.prefecture_code)

    try:
        # 1.4: 範囲解決に失敗した場合、いかなるHTTPリクエストも発生しないよう、
        # run_scope呼び出しより先にresolve_scopeで検証する(戻り値は使わず、
        # 例外の送出有無のみを見る。run_scopeが内部で改めて解決する)。
        resolve_scope(spec)
    except InvalidScopeError as error:
        print(f"範囲指定が不正です: {error}", file=sys.stderr)
        return 1

    result = run_scope(spec)
    failure_count = len(result.failed_site_keys) + len(result.failed_prefecture_codes)
    if failure_count > 0:
        print(
            f"{len(result.failed_site_keys)}サイト・{len(result.failed_prefecture_codes)}都道府県の処理に"
            "失敗しました(詳細はログを参照してください)",
            file=sys.stderr,
        )
        return 1
    return 0
