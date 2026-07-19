from dataclasses import FrozenInstanceError

import pytest

from roadstop_scraper.geojson import PREFECTURES
from roadstop_scraper.pipeline.scope import (
    REGIONS,
    InvalidScopeError,
    ScopeSpec,
    resolve_scope,
)


def test_全国解決の検証_regionもprefecture_codeも指定しない場合_全47都道府県をコード順で返す():
    # 両方省略時は全国範囲として、geojson.prefectures.PREFECTURESと同一集合・同一順序を返すことを確認する
    result = resolve_scope(ScopeSpec())

    assert result == PREFECTURES
    assert len(result) == 47


def test_地方指定の検証_hokkaidoを指定した場合_01の1件のみを返す():
    # 北海道地方は都道府県コード01の1件のみで構成されることを確認する
    result = resolve_scope(ScopeSpec(region="hokkaido"))

    assert [prefecture.code for prefecture in result] == ["01"]


def test_地方指定の検証_tohokuを指定した場合_02から07の6件をコード昇順で返す():
    # 東北地方は都道府県コード02〜07の6件で構成されることを確認する
    result = resolve_scope(ScopeSpec(region="tohoku"))

    assert [prefecture.code for prefecture in result] == [
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
    ]


def test_地方指定の検証_kyushu_okinawaを指定した場合_40から47の8件をコード昇順で返す():
    # 九州沖縄地方は都道府県コード40〜47の8件で構成されることを確認する
    result = resolve_scope(ScopeSpec(region="kyushu_okinawa"))

    assert [prefecture.code for prefecture in result] == [
        "40",
        "41",
        "42",
        "43",
        "44",
        "45",
        "46",
        "47",
    ]


def test_都道府県指定の検証_prefecture_codeを指定した場合_その1件のみを含む長さ1のタプルを返す():
    # 都道府県単位指定時は該当する1件のみを含むタプルとなることを確認する
    result = resolve_scope(ScopeSpec(prefecture_code="13"))

    assert len(result) == 1
    assert result[0].code == "13"
    assert result[0].name_ja == "東京都"


def test_異常系の検証_存在しない地方区分名を指定した場合_InvalidScopeErrorを送出する():
    # 対応表に存在しない地方区分名はInvalidScopeErrorとして拒否されることを確認する
    with pytest.raises(InvalidScopeError):
        resolve_scope(ScopeSpec(region="kanto2"))


def test_異常系の検証_存在しない都道府県コードを指定した場合_InvalidScopeErrorを送出する():
    # find_prefectureが解決できないコードはInvalidScopeErrorへ変換されることを確認する
    with pytest.raises(InvalidScopeError):
        resolve_scope(ScopeSpec(prefecture_code="99"))


def test_異常系の検証_regionとprefecture_codeを同時に指定した場合_InvalidScopeErrorを送出する():
    # 地方区分・都道府県の同時指定はInvalidScopeErrorとして拒否されることを確認する
    with pytest.raises(InvalidScopeError):
        resolve_scope(ScopeSpec(region="hokkaido", prefecture_code="01"))


def test_例外型の検証_InvalidScopeErrorが_送出された場合_ValueErrorとして捕捉できる():
    # 既存パッケージの例外パターン(ValueErrorサブクラス)に従うことを確認する
    with pytest.raises(ValueError):
        resolve_scope(ScopeSpec(region="unknown"))


def test_不変性の検証_ScopeSpecが_構築済みだった場合_属性の変更が禁止されている():
    # ScopeSpecがfrozen dataclassとして不変であることを確認する
    spec = ScopeSpec(prefecture_code="01")

    with pytest.raises(FrozenInstanceError):
        spec.prefecture_code = "02"


def test_対応表の検証_REGIONSが_定義済みだった場合_8区分の合計が47都道府県ちょうどで重複がない():
    # design.mdのInvariants(REGIONSの全区分の合計は47都道府県と一致し、重複を持たない)を直接検証する
    assert set(REGIONS.keys()) == {
        "hokkaido",
        "tohoku",
        "kanto",
        "chubu",
        "kinki",
        "chugoku",
        "shikoku",
        "kyushu_okinawa",
    }

    all_codes = [code for codes in REGIONS.values() for code in codes]

    assert len(all_codes) == 47
    assert len(set(all_codes)) == 47
    assert set(all_codes) == {prefecture.code for prefecture in PREFECTURES}
