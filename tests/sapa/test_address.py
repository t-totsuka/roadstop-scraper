"""住所の郵便番号分離と所在都道府県の導出(sapa.address)の検証。

タスク2.1の観測可能な完了条件を検証する: 郵便番号あり(〒あり/〒なし)/なしの
分離、47都道府県すべての導出、都道府県名を含まない住所での欠損がテストで
確認できること(design.md「sapa.address」節、research.md「Decision: 都道府県
の特定は詳細ページ住所の都道府県名前方一致で導出する」参照)。
"""

from __future__ import annotations

import pytest

from roadstop_scraper.geojson import PREFECTURES, Prefecture
from roadstop_scraper.sapa.address import find_prefecture_by_address, split_postal_address


class Test郵便番号分離:
    def test_郵便番号分離の検証_郵便記号付き郵便番号ありの住所だった場合_郵便番号と住所本体に分離される(self) -> None:
        postal_code, address = split_postal_address("〒349-0112 埼玉県蓮田市大字川島370番地")

        assert postal_code == "349-0112"
        assert address == "埼玉県蓮田市大字川島370番地"

    def test_郵便番号分離の検証_郵便記号なし郵便番号ありの住所だった場合_郵便番号と住所本体に分離される(self) -> None:
        postal_code, address = split_postal_address("349-0112 埼玉県蓮田市大字川島370番地")

        assert postal_code == "349-0112"
        assert address == "埼玉県蓮田市大字川島370番地"

    def test_郵便番号分離の検証_郵便番号なしの住所だった場合_郵便番号は欠損し原文がそのまま返る(self) -> None:
        raw = "埼玉県蓮田市大字川島370番地"

        postal_code, address = split_postal_address(raw)

        assert postal_code is None
        assert address == raw


class Test都道府県導出:
    @pytest.mark.parametrize("prefecture", PREFECTURES, ids=lambda p: p.code)
    def test_都道府県導出の検証_47都道府県それぞれの住所だった場合_対応するPrefectureが導出される(
        self, prefecture: Prefecture
    ) -> None:
        address = f"{prefecture.name_ja}なんとか市1-2-3"

        result = find_prefecture_by_address(address)

        assert result == prefecture

    def test_都道府県導出の検証_京都府と東京都のように部分文字列が重なる住所だった場合_衝突せず正しく導出される(
        self,
    ) -> None:
        kyoto = find_prefecture_by_address("京都府京都市中京区1-2-3")
        tokyo = find_prefecture_by_address("東京都千代田区1-2-3")

        assert kyoto is not None
        assert kyoto.name_ja == "京都府"
        assert tokyo is not None
        assert tokyo.name_ja == "東京都"

    def test_都道府県導出の検証_都道府県名を含まない住所だった場合_Noneが返る(self) -> None:
        result = find_prefecture_by_address("蓮田市大字川島370番地")

        assert result is None

    def test_都道府県導出の検証_空文字列だった場合_Noneが返る(self) -> None:
        result = find_prefecture_by_address("")

        assert result is None
