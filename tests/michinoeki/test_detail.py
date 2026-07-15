"""詳細ページからの付加情報抽出とプロパティへの変換(detail)の検証。

タスク3.2の観測可能な完了条件を検証する: フィクスチャHTMLから郵便番号分離・
駐車場台数(表記揺れを含む複数パターン)・施設設備タグ・ホームページ0/1/2件の
各ケースが正しく抽出できること、名称欠落時に構造変化として扱われること。
``roadstop_scraper.scraping.parse_html``で実際にフィクスチャHTML文字列を
パースし、``extract_station_properties``へ渡す結合的なテストとする
(research.md「詳細ページのDOM構造実測」参照)。
"""

from __future__ import annotations

import pytest

from roadstop_scraper.geojson import FacilityKind, Parking, find_prefecture
from roadstop_scraper.michinoeki.detail import extract_station_properties
from roadstop_scraper.scraping import StructureChangedError, parse_html


def _build_html(
    *,
    name_dd: str = "道の駅　三笠",
    address_dd: str = "068-2165 北海道三笠市岡山1056-1",
    tel_dd: str = "01267-2-3999",
    parking_dd: str = "大型：13台　普通車：202（身障者用2）台",
    opening_hours_dd: str = "9:00~17:00",
    homepage_dd: str = '<a href="https://example.com/a" target="_blank">https://example.com/a</a>',
    homepage2_dd: str = '<a href="https://example.com/b" target="_blank">https://example.com/b</a>',
    mapcode_dd: str = "180 276 269",
) -> str:
    # research.mdの実測どおり、.info配下にdl(dt/dd各1件)が8件並ぶ構造を再現する。
    return f"""
<html>
  <body>
    <div class="info">
      <dl><dt>道の駅名</dt><dd>{name_dd}</dd></dl>
      <dl><dt>所在地</dt><dd>{address_dd}</dd></dl>
      <dl><dt>TEL</dt><dd>{tel_dd}</dd></dl>
      <dl><dt>駐車場</dt><dd>{parking_dd}</dd></dl>
      <dl><dt>営業時間</dt><dd>{opening_hours_dd}</dd></dl>
      <dl><dt>ホームページ</dt><dd>{homepage_dd}</dd></dl>
      <dl><dt>ホームページ2</dt><dd>{homepage2_dd}</dd></dl>
      <dl><dt>マップコード</dt><dd>{mapcode_dd}</dd></dl>
    </div>
    <div class="viewFacility">
      <ul>
        <li><span>ATM</span></li>
        <li><span>EV充電施設</span></li>
        <li class="off"><span>給油所</span></li>
        <li class="off"><span>コンビニ</span></li>
      </ul>
    </div>
  </body>
</html>
"""


_FIXTURE_HTML_NAME_MISSING = """
<html>
  <body>
    <div class="info">
      <dl><dt>道の駅名</dt><dd></dd></dl>
      <dl><dt>所在地</dt><dd>068-2165 北海道三笠市岡山1056-1</dd></dl>
    </div>
    <div class="viewFacility">
      <ul></ul>
    </div>
  </body>
</html>
"""


_FIXTURE_HTML_ADDRESS_AND_PARKING_KEY_MISSING = """
<html>
  <body>
    <div class="info">
      <dl><dt>道の駅名</dt><dd>道の駅　最小構成</dd></dl>
      <dl><dt>TEL</dt><dd>01267-2-3999</dd></dl>
    </div>
    <div class="viewFacility">
      <ul></ul>
    </div>
  </body>
</html>
"""


def test_詳細抽出の検証_所在地_駐車場のdt_ddが丸ごと欠落する場合_該当項目のみNoneになる():
    prefecture = find_prefecture("01")
    page = parse_html(
        _FIXTURE_HTML_ADDRESS_AND_PARKING_KEY_MISSING,
        url="https://www.michi-no-eki.jp/stations/views/18786",
    )

    properties = extract_station_properties(
        page, prefecture, coordinate_source_url="https://www.michi-no-eki.jp/stations/views/18786"
    )

    assert properties.name == "道の駅　最小構成"
    assert properties.postal_code is None
    assert properties.address is None
    assert properties.parking is None
    assert properties.tel == "01267-2-3999"


def test_詳細抽出の検証_駐車場に身障者用の記載がない場合_disabledのみNoneになる():
    prefecture = find_prefecture("01")
    page = parse_html(
        _build_html(parking_dd="大型：5台　普通車：50台"),
        url="https://www.michi-no-eki.jp/stations/views/18786",
    )

    properties = extract_station_properties(
        page, prefecture, coordinate_source_url="https://www.michi-no-eki.jp/stations/views/18786"
    )

    assert properties.parking == Parking(large=5, standard=50, disabled=None)


def test_詳細抽出の検証_標準ケース_全項目が正しく抽出できる():
    prefecture = find_prefecture("01")
    page = parse_html(_build_html(), url="https://www.michi-no-eki.jp/stations/views/18786")

    properties = extract_station_properties(
        page, prefecture, coordinate_source_url="https://www.michi-no-eki.jp/stations/views/18786"
    )

    assert properties.name == "道の駅　三笠"
    assert properties.postal_code == "068-2165"
    assert properties.address == "北海道三笠市岡山1056-1"
    assert properties.tel == "01267-2-3999"
    assert properties.parking == Parking(large=13, standard=202, disabled=2)
    assert properties.opening_hours == "9:00~17:00"
    assert properties.websites == ("https://example.com/a", "https://example.com/b")
    assert properties.mapcode == "180 276 269"
    # off要素(給油所・コンビニ)は除外され、有効な2件のみが含まれる
    assert properties.facilities == ("ATM", "EV充電施設")


def test_詳細抽出の検証_駐車場のうち表記揺れ_身障者用の台数が正しく抽出できる():
    prefecture = find_prefecture("01")
    page = parse_html(
        _build_html(parking_dd="大型：9台　普通車：109（うち身障者用3）台"),
        url="https://www.michi-no-eki.jp/stations/views/18787",
    )

    properties = extract_station_properties(
        page, prefecture, coordinate_source_url="https://www.michi-no-eki.jp/stations/views/18787"
    )

    assert properties.parking == Parking(large=9, standard=109, disabled=3)


def test_詳細抽出の検証_ホームページ2が空文字の場合_websitesはホームページ1件のみになる():
    prefecture = find_prefecture("47")
    page = parse_html(
        _build_html(homepage2_dd='<a href="" target="_blank"></a>'),
        url="https://www.michi-no-eki.jp/stations/views/19814",
    )

    properties = extract_station_properties(
        page, prefecture, coordinate_source_url="https://www.michi-no-eki.jp/stations/views/19814"
    )

    assert properties.websites == ("https://example.com/a",)


def test_詳細抽出の検証_ホームページが0件の場合_websitesは空タプルになる():
    prefecture = find_prefecture("47")
    page = parse_html(
        _build_html(
            homepage_dd='<a href="" target="_blank"></a>',
            homepage2_dd='<a href="" target="_blank"></a>',
        ),
        url="https://www.michi-no-eki.jp/stations/views/19814",
    )

    properties = extract_station_properties(
        page, prefecture, coordinate_source_url="https://www.michi-no-eki.jp/stations/views/19814"
    )

    assert properties.websites == ()


def test_詳細抽出の検証_所在地が郵便番号パターンに一致しない場合_postal_codeとaddressはNoneになる():
    prefecture = find_prefecture("01")
    page = parse_html(
        _build_html(address_dd="住所不明(郵便番号なし)"),
        url="https://www.michi-no-eki.jp/stations/views/18786",
    )

    properties = extract_station_properties(
        page, prefecture, coordinate_source_url="https://www.michi-no-eki.jp/stations/views/18786"
    )

    assert properties.postal_code is None
    assert properties.address is None


def test_詳細抽出の検証_名称が取得できない場合_StructureChangedErrorが送出される():
    prefecture = find_prefecture("01")
    page = parse_html(_FIXTURE_HTML_NAME_MISSING, url="https://www.michi-no-eki.jp/stations/views/99999")

    with pytest.raises(StructureChangedError):
        extract_station_properties(
            page, prefecture, coordinate_source_url="https://www.michi-no-eki.jp/stations/views/99999"
        )


def test_詳細抽出の検証_pref_code_pref_name_kind_source_urlが正しく設定される():
    prefecture = find_prefecture("13")
    # page.urlとcoordinate_source_url引数を意図的に異なる値にし、
    # source_urlが引数の値そのままになる(page.urlを直接参照しない)ことを証明する。
    page = parse_html(_build_html(), url="https://www.michi-no-eki.jp/stations/views/00000")

    properties = extract_station_properties(
        page,
        prefecture,
        coordinate_source_url="https://www.michi-no-eki.jp/stations/views/12345",
    )

    assert properties.kind == FacilityKind.MICHINOEKI
    assert properties.pref_code == "13"
    assert properties.pref_name == "東京都"
    assert properties.source_url == "https://www.michi-no-eki.jp/stations/views/12345"
