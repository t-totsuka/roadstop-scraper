"""住所文字列の郵便番号分離と所在都道府県の導出。

「〒349-0112 埼玉県蓮田市…」形式の住所から郵便番号と住所本体を分離する
処理と、住所本体の先頭を47都道府県の日本語名と前方一致させて所在都道府県
を導出する処理を提供するモジュール(design.md「sapa.address」節参照)。

両関数とも純粋関数でありHTTP等のI/Oは行わない。都道府県を導出できない
場合は例外を送出せず``None``を返し、呼び出し側が抽出失敗(3.6)として
扱えるようにする。
"""

from __future__ import annotations

import re

from roadstop_scraper.geojson import PREFECTURES, Prefecture

__all__ = ["find_prefecture_by_address", "split_postal_address"]

# 「〒349-0112 埼玉県…」「349-0112 埼玉県…」のいずれの形式にも一致するよう、
# 先頭の〒記号を任意とする(research.mdの実測例参照。michinoeki/detail.pyの
# 郵便番号パターンと異なり、SA/PAの住所は〒記号付きで提供されうるため)。
_POSTAL_CODE_PATTERN = re.compile(r"^〒?(\d{3}-\d{4})\s*(.*)$")


def split_postal_address(raw: str) -> tuple[str | None, str]:
    """``raw`` を郵便番号と住所本体に分離する。

    「〒349-0112 埼玉県蓮田市…」「349-0112 埼玉県蓮田市…」のいずれの形式も
    (郵便番号, 住所本体)へ分離する。郵便番号パターンに一致しない場合は
    ``(None, raw)``(原文をそのまま住所本体として返す)。
    """
    match = _POSTAL_CODE_PATTERN.match(raw)
    if match is None:
        return None, raw
    return match.group(1), match.group(2)


def find_prefecture_by_address(address: str) -> Prefecture | None:
    """``address`` の先頭を47都道府県の日本語名と前方一致させて導出する。

    一致する都道府県名が見つからない場合は``None``を返す(呼び出し側で
    3.6の抽出失敗として扱う)。47都道府県名は前方一致で相互に衝突しない
    (「京都府」と「東京都」は先頭一致で区別される)。
    """
    for prefecture in PREFECTURES:
        if address.startswith(prefecture.name_ja):
            return prefecture
    return None
