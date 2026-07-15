from roadstop_scraper.geojson import PREFECTURES, find_prefecture
from roadstop_scraper.michinoeki.site_urls import (
    BASE_URL,
    SITE_PREFECTURE_CODES,
    build_search_url,
)

# design.md「Supporting References」の対応表(公式コード: サイト内コード)をそのまま転記する
_EXPECTED_SITE_PREFECTURE_CODES = {
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


def test_対応表の件数の検証_SITE_PREFECTURE_CODESが_定義済みだった場合_47件である():
    # design.mdのInvariants(SITE_PREFECTURE_CODESは47件)を直接検証する
    assert len(SITE_PREFECTURE_CODES) == 47


def test_対応表の重複の検証_SITE_PREFECTURE_CODESが_定義済みだった場合_サイト内コードの値に重複がない():
    # design.mdのInvariants(重複なし)を、値集合のサイズがキー集合のサイズと一致することで検証する
    assert len(set(SITE_PREFECTURE_CODES.values())) == len(SITE_PREFECTURE_CODES)


def test_対応表の網羅性の検証_SITE_PREFECTURE_CODESが_定義済みだった場合_PREFECTURESの全コードを過不足なくカバーする():
    # design.mdのInvariants(PREFECTURESの全コードをカバーする)をキー集合の一致で検証する
    assert set(SITE_PREFECTURE_CODES.keys()) == {prefecture.code for prefecture in PREFECTURES}


def test_対応表の内容の検証_SITE_PREFECTURE_CODESが_定義済みだった場合_design_mdの対応表と完全に一致する():
    # design.md「Supporting References」に記載された全47件の対応をそのまま突き合わせる
    assert dict(SITE_PREFECTURE_CODES) == _EXPECTED_SITE_PREFECTURE_CODES


def test_対応表の個別値の検証_北海道の場合_公式コード01がサイト内コード10に対応する():
    assert SITE_PREFECTURE_CODES["01"] == "10"


def test_対応表の個別値の検証_沖縄県の場合_公式コード47がサイト内コード56に対応する():
    assert SITE_PREFECTURE_CODES["47"] == "56"


def test_対応表の個別値の検証_東京都の場合_公式コード13がサイト内コード22に対応する():
    assert SITE_PREFECTURE_CODES["13"] == "22"


def test_対応表の個別値の検証_福岡県の場合_公式コード40がサイト内コード49に対応する():
    assert SITE_PREFECTURE_CODES["40"] == "49"


def test_URL構築の検証_北海道を指定した場合_サイト内コード10を用いた絶対URLを返す():
    prefecture = find_prefecture("01")

    assert build_search_url(prefecture) == f"{BASE_URL}/stations/search/10/all/all"


def test_URL構築の検証_沖縄県を指定した場合_サイト内コード56を用いた絶対URLを返す():
    prefecture = find_prefecture("47")

    assert build_search_url(prefecture) == f"{BASE_URL}/stations/search/56/all/all"


def test_URL構築の検証_47都道府県すべてについて_対応するサイト内コードを用いた絶対URLを構築できる():
    # 観測可能な完了条件: 47都道府県すべてについて正しいURLが構築できることを全件ループで確認する
    for prefecture in PREFECTURES:
        expected_site_code = SITE_PREFECTURE_CODES[prefecture.code]

        assert (
            build_search_url(prefecture) == f"https://www.michi-no-eki.jp/stations/search/{expected_site_code}/all/all"
        )


def test_URL構築の検証_BASE_URLの検証_定義済みの値が対象サイトのオリジンと一致する():
    assert BASE_URL == "https://www.michi-no-eki.jp"
