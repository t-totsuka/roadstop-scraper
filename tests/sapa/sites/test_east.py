"""NEXCO東日本(driveplaza.com)サイトアダプタ(east)の検証(タスク3.1)。

実測(research.md、およびタスク3.1実施時の追加実測)に基づくフィクスチャHTMLで
一覧・詳細の抽出が期待どおり動作すること、上り・下りが別スタブ・別詳細として
扱われることを検証する。実サイトへのライブHTTPアクセスは行わない
(全てローカルのフィクスチャHTML文字列を``parse_html``でパースして検証する)。
"""

from __future__ import annotations

import pytest

from roadstop_scraper.geojson import Direction, Parking, find_prefecture
from roadstop_scraper.sapa.sites import SapaDetail, SapaListingResult, SapaStub
from roadstop_scraper.sapa.sites.east import EastSite
from roadstop_scraper.scraping import StructureChangedError, parse_html

_LISTING_URL = "https://www.driveplaza.com/dp/SAPAServRes?arealist=2&HIGHWAY=AA"

# 実測(research.md、東北自動車道 蓮田ＳＡ)を模した一覧フィクスチャ。
# 3件目は名称が空(構造変化ではなく個別要素の解釈不能)の要素であり、
# URLは確認できるがスタブ化はできないケースを表す。
_FIXTURE_LISTING_HTML = """
<html>
  <body>
    <main>
      <div class="c-roundbox has-shadow box-sapa">
        <div class="c-pcflex">
          <div class="c-col">
            <div class="ttl-wrap">
              <span class="txt-road">東北自動車道</span>
              <h3 class="ttl-sapaName">
                <a href="http://www.driveplaza.com/sapa/1040/1040021/1/" class="c-link has-animIcon" id="click_dp-SAPAServRes_sapa-detail">蓮田ＳＡ(上)<i class="icon-caret-right circle"></i></a>
              </h3>
              <span class="txt-info">大型：132／小型：354</span>
            </div>
            <ul class="li-icons">
              <li><img src="/assets/img/common/icon_shisetsu_green_01.svg" alt="軽食・カフェ・レストランのアイコン"></li>
            </ul>
          </div>
        </div>
      </div>
      <div class="c-roundbox has-shadow box-sapa">
        <div class="c-pcflex">
          <div class="c-col">
            <div class="ttl-wrap">
              <span class="txt-road">東北自動車道</span>
              <h3 class="ttl-sapaName">
                <a href="http://www.driveplaza.com/sapa/1040/1040021/2/" class="c-link has-animIcon" id="click_dp-SAPAServRes_sapa-detail">蓮田ＳＡ(下)<i class="icon-caret-right circle"></i></a>
              </h3>
              <span class="txt-info">大型：120／小型：300</span>
            </div>
          </div>
        </div>
      </div>
      <div class="c-roundbox has-shadow box-sapa">
        <div class="c-pcflex">
          <div class="c-col">
            <div class="ttl-wrap">
              <span class="txt-road">構造テスト線</span>
              <h3 class="ttl-sapaName">
                <a href="http://www.driveplaza.com/sapa/9999/9999999/1/"></a>
              </h3>
              <span class="txt-info"></span>
            </div>
          </div>
        </div>
      </div>
    </main>
  </body>
</html>
"""

_FIXTURE_LISTING_HTML_NO_ELEMENTS = """
<html>
  <body>
    <main>
      <p>該当するSA/PAはありません</p>
    </main>
  </body>
</html>
"""


def _build_template_a_html(
    *,
    name: str = "羽生PA",
    ruby: str = "はにゅう",
    road_name: str = "東北自動車道",
    direction_label: str = "上り",
    address_p: str = "〒348-0004 埼玉県羽生市弥勒字五軒1686",
    parking_dd: str = "大型　148 ／ 小型　114",
) -> str:
    # research.md/タスク3.1実測(羽生PA上り、テンプレートA)を模したフィクスチャ。
    return f"""
<html>
  <head><title>{name}({direction_label})・{road_name} | ドラぷら(NEXCO東日本)</title></head>
  <body>
    <div class="title-wrap">
      <span class="txt-way">{road_name}</span>
      <h1 class="c-titleH1 has-ruby">
        <span class="txt-ruby">{ruby}</span>
        <span class="txt-title">{name}</span>
      </h1>
      <span class="c-labelRight">{direction_label}</span>
    </div>
    <div class="box-facility">
      <div class="box-info">
        <p>{address_p}</p>
        <dl class="li-info">
          <dt>駐車場</dt>
          <dd>{parking_dd}</dd>
          <dt>トイレ</dt>
          <dd>男　大17 、小36 ／ 女　58</dd>
        </dl>
      </div>
    </div>
  </body>
</html>
"""


def _build_template_b_html(
    *,
    name: str = "Pasar蓮田",
    road_name: str = "東北自動車道",
    direction_label: str = "上り",
    address_p: str = "〒349-0112 埼玉県蓮田市大字川島370番地",
    parking_dd: str = "大型：132／小型：354",
) -> str:
    # research.md/タスク3.1実測(Pasar蓮田上り、テンプレートB)を模したフィクスチャ。
    return f"""
<html>
  <head><title>Pasar ( パサール ) {name}({direction_label}線)・{road_name} | サービスエリア | ドラぷら</title></head>
  <body>
    <div class="cont_information-text">
      <h2>{name}・{direction_label}</h2>
      <p>{address_p}</p>
    </div>
    <dl class="cont_information-info">
      <dt>サービスエリア・コンシェルジェ</dt>
      <dd>【平日】9:00～19:00<br>【土日祝】8:00～20:00</dd>
    </dl>
    <dl class="cont_information-park">
      <dt>駐車場</dt>
      <dd>{parking_dd}</dd>
    </dl>
    <dl class="cont_information-toilet">
      <dt>トイレ</dt>
      <dd>男：大25／小32　女：99</dd>
    </dl>
  </body>
</html>
"""


_FIXTURE_NO_TEMPLATE_MATCH_HTML = """
<html>
  <body>
    <p>ページが見つかりません</p>
  </body>
</html>
"""


class TestURL帰属判定:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.driveplaza.com/sapa/1040/1040021/1/",
            "http://www.driveplaza.com/dp/SAPAServRes?arealist=1&HIGHWAY=AA",
            "https://driveplaza.com/sapa/1040/1040021/1/",
        ],
    )
    def test_URL帰属判定の検証_driveplaza_comのホストだった場合_Trueが返る(self, url: str) -> None:
        assert EastSite().owns_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://c-nexco.co.jp/sapa/1/",
            "https://driveplaza.com.evil.example/sapa/1/",
            "https://evil-driveplaza.com/sapa/1/",
            "https://www.michi-no-eki.jp/stations/views/1",
        ],
    )
    def test_URL帰属判定の検証_別ホストのURLだった場合_Falseが返る(self, url: str) -> None:
        assert EastSite().owns_url(url) is False


class Test一覧URL構成:
    def test_一覧URL構成の検証_北海道のみ指定された場合_arealist1のURLのみ返る(self) -> None:
        urls = EastSite().listing_urls((find_prefecture("01"),))

        assert urls == ("https://www.driveplaza.com/dp/SAPAServRes?arealist=1&HIGHWAY=AA",)

    def test_一覧URL構成の検証_九州の都道府県のみ指定された場合_空タプルが返る(self) -> None:
        urls = EastSite().listing_urls((find_prefecture("40"),))

        assert urls == ()

    def test_一覧URL構成の検証_関東と新潟が混在する場合_arealist3と4のURLが返る(self) -> None:
        urls = EastSite().listing_urls((find_prefecture("11"), find_prefecture("15")))

        assert urls == (
            "https://www.driveplaza.com/dp/SAPAServRes?arealist=3&HIGHWAY=AA",
            "https://www.driveplaza.com/dp/SAPAServRes?arealist=4&HIGHWAY=AA",
        )

    def test_一覧URL構成の検証_都道府県が指定されない場合_空タプルが返る(self) -> None:
        urls = EastSite().listing_urls(())

        assert urls == ()


class Test一覧パース:
    def test_一覧パースの検証_上り下りの一対のフィクスチャだった場合_2件のスタブがscheme正規化済みURLで抽出される(
        self,
    ) -> None:
        page = parse_html(_FIXTURE_LISTING_HTML, url=_LISTING_URL)

        result = EastSite().parse_listing(page)

        assert isinstance(result, SapaListingResult)
        assert result.stubs == (
            SapaStub(display_name="蓮田ＳＡ(上)", detail_url="https://www.driveplaza.com/sapa/1040/1040021/1/"),
            SapaStub(display_name="蓮田ＳＡ(下)", detail_url="https://www.driveplaza.com/sapa/1040/1040021/2/"),
        )

    def test_一覧パースの検証_名称が空の要素だった場合_スキップされるがURLはlisted_urlsに残る(self) -> None:
        page = parse_html(_FIXTURE_LISTING_HTML, url=_LISTING_URL)

        result = EastSite().parse_listing(page)

        assert result.skipped_count == 1
        assert result.listed_urls == frozenset(
            {
                "https://www.driveplaza.com/sapa/1040/1040021/1/",
                "https://www.driveplaza.com/sapa/1040/1040021/2/",
                "https://www.driveplaza.com/sapa/9999/9999999/1/",
            }
        )

    def test_一覧パースの検証_上りと下りは別のスタブとして扱われる(self) -> None:
        page = parse_html(_FIXTURE_LISTING_HTML, url=_LISTING_URL)

        result = EastSite().parse_listing(page)

        up_stub, down_stub = result.stubs
        assert up_stub != down_stub
        assert up_stub.detail_url != down_stub.detail_url
        assert up_stub.display_name != down_stub.display_name

    def test_一覧パースの検証_box_sapa要素が0件の場合_空のスタブと空のlisted_urlsが返る(self) -> None:
        page = parse_html(_FIXTURE_LISTING_HTML_NO_ELEMENTS, url=_LISTING_URL)

        result = EastSite().parse_listing(page)

        assert result.stubs == ()
        assert result.listed_urls == frozenset()
        assert result.skipped_count == 0


class Test詳細抽出テンプレートA:
    def test_詳細抽出の検証_テンプレートAの上りフィクスチャだった場合_名称路線名方向住所駐車場が正しく抽出される(
        self,
    ) -> None:
        page = parse_html(_build_template_a_html(), url="https://www.driveplaza.com/sapa/1040/1040041/1/")

        detail = EastSite().extract_detail(page, detail_url=page.url)

        assert isinstance(detail, SapaDetail)
        assert detail.name == "羽生PA"
        assert detail.road_name == "東北自動車道"
        assert detail.direction is Direction.UP
        assert detail.postal_code == "348-0004"
        assert detail.address == "埼玉県羽生市弥勒字五軒1686"
        assert detail.parking == Parking(large=148, standard=114, disabled=None)
        assert detail.coordinate is None

    def test_詳細抽出の検証_テンプレートAの下りフィクスチャだった場合_directionが下りになる(self) -> None:
        page = parse_html(
            _build_template_a_html(direction_label="下り"),
            url="https://www.driveplaza.com/sapa/1040/1040041/2/",
        )

        detail = EastSite().extract_detail(page, detail_url=page.url)

        assert detail.direction is Direction.DOWN

    def test_詳細抽出の検証_住所と駐車場のdt_ddが丸ごと欠落する場合_該当項目のみNoneになる(self) -> None:
        html = """
<html>
  <head><title>最小構成PA(上)・テスト線 | ドラぷら(NEXCO東日本)</title></head>
  <body>
    <div class="title-wrap">
      <span class="txt-way">テスト線</span>
      <h1 class="c-titleH1 has-ruby">
        <span class="txt-ruby">さいしょう</span>
        <span class="txt-title">最小構成PA</span>
      </h1>
      <span class="c-labelRight">上り</span>
    </div>
    <div class="box-facility">
      <div class="box-info"></div>
    </div>
  </body>
</html>
"""
        page = parse_html(html, url="https://www.driveplaza.com/sapa/0/0/1/")

        detail = EastSite().extract_detail(page, detail_url=page.url)

        assert detail.name == "最小構成PA"
        assert detail.address is None
        assert detail.postal_code is None
        assert detail.parking is None


class Test詳細抽出テンプレートB:
    def test_詳細抽出の検証_テンプレートBの上りフィクスチャだった場合_名称路線名方向住所駐車場営業時間が正しく抽出される(
        self,
    ) -> None:
        page = parse_html(_build_template_b_html(), url="https://www.driveplaza.com/sapa/1040/1040021/1/")

        detail = EastSite().extract_detail(page, detail_url=page.url)

        assert detail.name == "Pasar蓮田"
        assert detail.road_name == "東北自動車道"
        assert detail.direction is Direction.UP
        assert detail.postal_code == "349-0112"
        assert detail.address == "埼玉県蓮田市大字川島370番地"
        assert detail.parking == Parking(large=132, standard=354, disabled=None)
        assert detail.opening_hours == "【平日】9:00～19:00【土日祝】8:00～20:00"
        assert detail.coordinate is None

    def test_詳細抽出の検証_テンプレートBの下りフィクスチャだった場合_directionが下りになる(self) -> None:
        page = parse_html(
            _build_template_b_html(direction_label="下り"),
            url="https://www.driveplaza.com/sapa/1040/1040021/2/",
        )

        detail = EastSite().extract_detail(page, detail_url=page.url)

        assert detail.direction is Direction.DOWN

    def test_詳細抽出の検証_titleタグが存在しない場合_road_nameはNoneになる(self) -> None:
        html = """
<html>
  <body>
    <div class="cont_information-text">
      <h2>タイトル欠落施設・上り</h2>
      <p>〒000-0000 テスト県テスト市9-9</p>
    </div>
  </body>
</html>
"""
        page = parse_html(html, url="https://www.driveplaza.com/sapa/0/1/1/")

        detail = EastSite().extract_detail(page, detail_url=page.url)

        assert detail.name == "タイトル欠落施設"
        assert detail.road_name is None
        assert detail.direction is Direction.UP


class Test上り下りは別データとして扱われる:
    def test_詳細抽出の検証_同一施設の上りと下りのフィクスチャだった場合_directionが異なり別データになる(self) -> None:
        up_page = parse_html(_build_template_a_html(direction_label="上り"), url="https://www.driveplaza.com/x/1/")
        down_page = parse_html(_build_template_a_html(direction_label="下り"), url="https://www.driveplaza.com/x/2/")

        up_detail = EastSite().extract_detail(up_page, detail_url=up_page.url)
        down_detail = EastSite().extract_detail(down_page, detail_url=down_page.url)

        assert up_detail != down_detail
        assert up_detail.direction is Direction.UP
        assert down_detail.direction is Direction.DOWN


class Test構造変化の検知:
    def test_詳細抽出の検証_両テンプレートいずれの名称も取得できない場合_StructureChangedErrorが送出される(
        self,
    ) -> None:
        page = parse_html(_FIXTURE_NO_TEMPLATE_MATCH_HTML, url="https://www.driveplaza.com/sapa/0/0/1/")

        with pytest.raises(StructureChangedError):
            EastSite().extract_detail(page, detail_url=page.url)


class Test上り下り以外の方向表記:
    def test_詳細抽出の検証_内回りのような上り下り以外の表記だった場合_directionはNoneになる(self) -> None:
        page = parse_html(
            _build_template_a_html(direction_label="内回り", road_name="首都圏中央連絡自動車道", name="厚木PA"),
            url="https://www.driveplaza.com/sapa/1/1/1/",
        )

        detail = EastSite().extract_detail(page, detail_url=page.url)

        assert detail.direction is None
        assert detail.name == "厚木PA"

    def test_詳細抽出の検証_方向表記が存在しない場合_directionはNoneになる(self) -> None:
        html = """
<html>
  <head><title>集約施設・国道テスト線 | ドラぷら(NEXCO東日本)</title></head>
  <body>
    <div class="title-wrap">
      <span class="txt-way">国道テスト線</span>
      <h1 class="c-titleH1 has-ruby">
        <span class="txt-ruby">しゅうやく</span>
        <span class="txt-title">集約施設</span>
      </h1>
    </div>
    <div class="box-facility">
      <div class="box-info">
        <p>〒000-0000 テスト県テスト市1-1</p>
        <dl class="li-info">
          <dt>駐車場</dt>
          <dd>大型　10 ／ 小型　20</dd>
        </dl>
      </div>
    </div>
  </body>
</html>
"""
        page = parse_html(html, url="https://www.driveplaza.com/sapa/2/2/1/")

        detail = EastSite().extract_detail(page, detail_url=page.url)

        assert detail.direction is None
        assert detail.name == "集約施設"
