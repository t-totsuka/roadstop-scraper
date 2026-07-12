import dataclasses
import importlib
import re

import pytest

from roadstop_scraper.geojson.prefectures import (
    PREFECTURES,
    UnknownPrefectureError,
    find_prefecture,
)


def test_geojsonパッケージの検証_importが要求された場合_成功する():
    # geojsonサブパッケージが公開importパスとして存在することを確認する
    module = importlib.import_module("roadstop_scraper.geojson")

    assert module is not None


def test_対応表の検証_PREFECTURESが_定義済みだった場合_47件でコード昇順かつ重複なしである():
    # 全国地方公共団体コード準拠の47件が番号昇順・重複なしで並ぶことを確認する
    codes = [prefecture.code for prefecture in PREFECTURES]

    assert len(PREFECTURES) == 47
    assert codes == sorted(codes)
    assert len(set(codes)) == 47


def test_対応表の検証_各Prefectureが_定義済みだった場合_コードは2桁ローマ字は小文字英字である():
    # コードはゼロ埋め2桁("01"〜"47")、ローマ字名は命名規則で使える小文字英字のみ、
    # 日本語名は非空であることを確認する
    for prefecture in PREFECTURES:
        assert re.fullmatch(r"(0[1-9]|[1-3][0-9]|4[0-7])", prefecture.code)
        assert re.fullmatch(r"[a-z]+", prefecture.romaji)
        assert prefecture.name_ja != ""


def test_対応表の検証_ローマ字名が_47件定義済みだった場合_重複なしである():
    # ローマ字名がファイル名の構成要素として一意に使えることを確認する
    romaji_names = [prefecture.romaji for prefecture in PREFECTURES]

    assert len(set(romaji_names)) == 47


def test_参照関数の検証_find_prefectureが_既知のコードだった場合_対応するPrefectureを返す():
    # 先頭・末尾・中間のコードで対応表の内容が正しく引けることを確認する
    hokkaido = find_prefecture("01")
    tokyo = find_prefecture("13")
    okinawa = find_prefecture("47")

    assert (hokkaido.romaji, hokkaido.name_ja) == ("hokkaido", "北海道")
    assert (tokyo.romaji, tokyo.name_ja) == ("tokyo", "東京都")
    assert (okinawa.romaji, okinawa.name_ja) == ("okinawa", "沖縄県")


@pytest.mark.parametrize("unknown_code", ["00", "48", "1", "001", "ab", ""])
def test_参照関数の検証_find_prefectureが_未知のコードだった場合_専用例外を送出する(
    unknown_code,
):
    # 範囲外・桁数違い・非数値のコードがUnknownPrefectureErrorで拒否されることを確認する
    with pytest.raises(UnknownPrefectureError):
        find_prefecture(unknown_code)


def test_例外型の検証_UnknownPrefectureErrorが_送出された場合_ValueErrorとして捕捉できる():
    # 既存commonパッケージの例外パターン(ValueErrorサブクラス)に従うことを確認する
    with pytest.raises(ValueError):
        find_prefecture("99")


def test_不変性の検証_Prefectureが_構築済みだった場合_属性の変更が禁止されている():
    # 参照データが実行中に書き換えられないことを確認する
    prefecture = find_prefecture("01")

    with pytest.raises(dataclasses.FrozenInstanceError):
        prefecture.code = "99"
