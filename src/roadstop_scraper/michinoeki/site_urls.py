"""対象サイト固有の都道府県コード対応表と一覧ページURLの構築。

対象サイト(michi-no-eki.jp)は公式都道府県コード("01"〜"47")とは異なる
独自のコード体系("10"〜"56")で都道府県を識別する。この対応表は本モジュールが
唯一の正であり、一覧ページURL(検索ページURL)の構築のみを担う。詳細ページURLは
一覧ページの``data-link``属性から得られるため、本モジュールでは構築しない。
"""

from __future__ import annotations

from collections.abc import Mapping

from roadstop_scraper.geojson import Prefecture

__all__ = ["BASE_URL", "SITE_PREFECTURE_CODES", "build_search_url"]

BASE_URL = "https://www.michi-no-eki.jp"
"""対象サイトのオリジン。"""

SITE_PREFECTURE_CODES: Mapping[str, str] = {
    "01": "10",
    "02": "11",
    "03": "13",
    "04": "14",
    "05": "12",
    "06": "15",
    "07": "16",
    "08": "17",
    "09": "18",
    "10": "19",
    "11": "20",
    "12": "21",
    "13": "22",
    "14": "23",
    "15": "24",
    "16": "25",
    "17": "26",
    "18": "27",
    "19": "28",
    "20": "29",
    "21": "30",
    "22": "31",
    "23": "32",
    "24": "33",
    "25": "34",
    "26": "35",
    "27": "36",
    "28": "37",
    "29": "38",
    "30": "39",
    "31": "40",
    "32": "41",
    "33": "42",
    "34": "43",
    "35": "44",
    "36": "45",
    "37": "46",
    "38": "47",
    "39": "48",
    "40": "49",
    "41": "50",
    "42": "51",
    "43": "52",
    "44": "53",
    "45": "54",
    "46": "55",
    "47": "56",
}
"""公式都道府県コード("01"〜"47") -> サイト内都道府県コード("10"〜"56")。47件。"""


def build_search_url(prefecture: Prefecture) -> str:
    """一覧/検索ページの絶対URLを返す。

    ``prefecture.code``を``SITE_PREFECTURE_CODES``でサイト内コードへ変換し、
    ``{BASE_URL}/stations/search/{サイト内コード}/all/all``を構築する。
    ``prefecture``は``geojson.prefectures.PREFECTURES``に含まれる47件の
    いずれかであることを前提とするため、単純な辞書引きで解決する。
    """
    site_code = SITE_PREFECTURE_CODES[prefecture.code]
    return f"{BASE_URL}/stations/search/{site_code}/all/all"
