"""NEXCO中日本(sapa.c-nexco.co.jp)サイトアダプタ(central)の検証(タスク3.2)。

実測(タスク3.2実施時の実測)に基づくフィクスチャHTMLで一覧・詳細の抽出が
期待どおり動作すること、ページネーションを跨いだ場合でも``parse_listing``が
ページ非依存に動作すること、上り・下りが別データとして扱われることを検証
する。実サイトへのライブHTTPアクセスは行わない(全てローカルのフィクスチャ
HTML文字列を``parse_html``でパースして検証する)。

一覧ページのページネーション自体は静的解析では再現できなかった既知の制限
(central.pyのモジュールdocstring参照)のため、``listing_urls``は1ページ目の
URLのみを返す仕様である。そのため本テストスイートの「ページネーション」
関連テストは、``parse_listing``単体が「どのページのHTMLを渡されても同じ
ロジックで正しくパースできる(ページ非依存)」ことを、2つの独立したフィクスチャ
ページ(擬似的な1・2ページ目)にそれぞれ``parse_listing``を適用し結果を結合
することで証明するものであり、``listing_urls``による実際の複数ページ取得
そのものを検証するものではない(その点は明示的にタスク6.3のフォローアップ
対象)。
"""

from __future__ import annotations

import pytest

from roadstop_scraper.geojson import Direction, Parking, find_prefecture
from roadstop_scraper.sapa.sites import SapaDetail, SapaListingResult, SapaStub
from roadstop_scraper.sapa.sites.central import CentralSite
from roadstop_scraper.scraping import StructureChangedError, parse_html

_SEARCH_RESULT_URL = "https://sapa.c-nexco.co.jp/search/result"

# 実測(research.md、港北PA)を模した一覧フィクスチャ(1ページ目)。
# div#page_sp(モバイル用)にも同一データを重複配置し、div#pageのみを対象に
# することで二重カウントしないことを検証する。
# div#page側には以下の行を含める:
#   1. 港北PA（上り）(sapainfoid=17、正常)
#   2. 港北PA（下り）(sapainfoid=18、正常)
#   3. 名称不明PA（上り）(リンクなし=href欠落。skipped_countの検証用)
#   4. 名前が空(href=sapainfoid=99はあるがリンクテキストが空。listed_urlsは
#      残るがstub化されない、east.pyの前例と同様のケースの検証用)
_FIXTURE_LISTING_PAGE1_HTML = """
<html>
  <body>
    <div id="page_sp">
      <div class="mod-table-sp">
        <table summary="検索結果">
          <tr class="tableTr-SP">
            <th>路線名</th>
            <th>エリア名</th>
            <th>検索一致項目</th>
          </tr>
          <tr class="tableTr-SP">
            <td>東名高速道路</td>
            <td><a href="/sapa?sapainfoid=17">港北PA（上り）</a></td>
            <td class="lastchild"><dl class="side"></dl></td>
          </tr>
          <tr class="tableTr-SP">
            <td>東名高速道路</td>
            <td><a href="/sapa?sapainfoid=18">港北PA（下り）</a></td>
            <td class="lastchild"><dl class="side"></dl></td>
          </tr>
        </table>
      </div>
    </div>
    <div id="page">
      <div class="mod-table">
        <table summary="検索結果">
          <caption>1－20件／216件中</caption>
          <tr class="tableTr">
            <th width="20%">路線名</th>
            <th width="20%">エリア名</th>
            <th width="60%">検索一致項目 </th>
          </tr>
          <tr class="tableTr">
            <td>東名高速道路</td>
            <td><a href="/sapa?sapainfoid=17">港北PA（上り）</a></td>
            <td class="lastchild"><dl class="side"></dl></td>
          </tr>
          <tr class="lastTr">
            <td class="lastchild" colspan="2">
              <div class="tt">検索一致項目</div>
              <dl class="side noData"></dl>
            </td>
          </tr>
          <tr class="tableTr">
            <td>東名高速道路</td>
            <td><a href="/sapa?sapainfoid=18">港北PA（下り）</a></td>
            <td class="lastchild"><dl class="side"></dl></td>
          </tr>
          <tr class="lastTr">
            <td class="lastchild" colspan="2">
              <div class="tt">検索一致項目</div>
              <dl class="side noData"></dl>
            </td>
          </tr>
          <tr class="tableTr">
            <td>東名高速道路</td>
            <td><a>名称不明PA（上り）</a></td>
            <td class="lastchild"><dl class="side"></dl></td>
          </tr>
          <tr class="lastTr">
            <td class="lastchild" colspan="2">
              <div class="tt">検索一致項目</div>
              <dl class="side noData"></dl>
            </td>
          </tr>
          <tr class="tableTr">
            <td>東名高速道路</td>
            <td><a href="/sapa?sapainfoid=99"></a></td>
            <td class="lastchild"><dl class="side"></dl></td>
          </tr>
          <tr class="lastTr">
            <td class="lastchild" colspan="2">
              <div class="tt">検索一致項目</div>
              <dl class="side noData"></dl>
            </td>
          </tr>
        </table>
      </div>
    </div>
  </body>
</html>
"""

# 擬似的な「2ページ目」フィクスチャ(EXPASA海老名の上り・下りを模した、
# 1ページ目と異なる施設データ)。parse_listing自体のページ非依存性を
# 証明するためのものであり、実際のページネーション取得(listing_urls)を
# 検証するものではない(モジュールdocstring・本ファイルdocstring参照)。
_FIXTURE_LISTING_PAGE2_HTML = """
<html>
  <body>
    <div id="page">
      <div class="mod-table">
        <table summary="検索結果">
          <caption>21－40件／216件中</caption>
          <tr class="tableTr">
            <th width="20%">路線名</th>
            <th width="20%">エリア名</th>
            <th width="60%">検索一致項目 </th>
          </tr>
          <tr class="tableTr">
            <td>東名高速道路</td>
            <td><a href="/sapa?sapainfoid=200">EXPASA海老名（上り）</a></td>
            <td class="lastchild"><dl class="side"></dl></td>
          </tr>
          <tr class="lastTr">
            <td class="lastchild" colspan="2">
              <div class="tt">検索一致項目</div>
              <dl class="side noData"></dl>
            </td>
          </tr>
          <tr class="tableTr">
            <td>東名高速道路</td>
            <td><a href="/sapa?sapainfoid=201">EXPASA海老名（下り）</a></td>
            <td class="lastchild"><dl class="side"></dl></td>
          </tr>
          <tr class="lastTr">
            <td class="lastchild" colspan="2">
              <div class="tt">検索一致項目</div>
              <dl class="side noData"></dl>
            </td>
          </tr>
        </table>
      </div>
    </div>
  </body>
</html>
"""

_FIXTURE_LISTING_HTML_NO_ELEMENTS = """
<html>
  <body>
    <div id="page">
      <div class="mod-table">
        <table summary="検索結果">
          <tr class="tableTr">
            <th width="20%">路線名</th>
            <th width="20%">エリア名</th>
            <th width="60%">検索一致項目 </th>
          </tr>
        </table>
      </div>
    </div>
  </body>
</html>
"""


def _build_detail_html(
    *,
    name: str = "港北PA",
    direction_label: str = "上り",
    area_direction: str = "東京方面",
    road_code: str = "E1",
    road_name: str = "東名高速道路",
    address: str = "神奈川県横浜市緑区",
    parking_text: str = "大型：25/小型：68（大型との兼用を含む）",
    map_href: str | None = (
        "https://www.google.com/maps/place/%E6%B8%AF%E5%8C%97PA+(%E4%B8%8A%E3%82%8A)/"
        "@35.53287,139.526834,17z/data=!3m1!4b1!4m6!3m5!1s0x6018f81fc43fd8c9:0xa3e0a29c2ebc3008"
        "!8m2!3d35.53287!4d139.526834!16s%2Fg%2F11g8748kqm?entry=ttu"
    ),
) -> str:
    # research.md/タスク3.2実測(港北PA上り)を模したフィクスチャ。
    # .sapa_summary最初のpは路線コードと路線名が改行・空白で連結される
    # (実際のインデント・改行を再現し、単純化した1行ノードにはしない)。
    map_anchor = (
        f'<a href="{map_href}" target="_blank"><img src="/shared/img/sapa/btn_googlemap_link.png" /></a>'
        if map_href
        else ""
    )
    return f"""
<html>
  <body>
    <div class="mod-box sp_rightBox sp_R03">
      <div class="mod-box-inset sapa_summary">
        <p>
            <span style="margin-right:5px;">{road_code}</span>
            {road_name}
        </p>
        <h3 class="heading">{name}（{direction_label}：{area_direction}）</h3>
        <p class="address">
            {address}
        </p>
        <p class="ico-parking">
            <img src="/shared/img/sapa/ico/ico_parking_02.png" height="15" width="15">
            {parking_text}
        </p>
        <p class="ico-toilet">
            男：大3／女：3
        </p>
        <p class="ico-disabilities"></p>
      </div>
    </div>
    {map_anchor}
  </body>
</html>
"""


_FIXTURE_NO_HEADING_HTML = """
<html>
  <body>
    <div class="mod-box-inset sapa_summary">
      <p><span>E1</span> 東名高速道路</p>
      <p class="address">神奈川県横浜市緑区</p>
    </div>
  </body>
</html>
"""


class TestURL帰属判定:
    @pytest.mark.parametrize(
        "url",
        [
            "https://sapa.c-nexco.co.jp/sapa?sapainfoid=17",
            "http://sapa.c-nexco.co.jp/search/result",
        ],
    )
    def test_URL帰属判定の検証_sapa_c_nexco_co_jpのホストだった場合_Trueが返る(self, url: str) -> None:
        assert CentralSite().owns_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://sapa.c-nexco.co.jp.evil.example/sapa?sapainfoid=17",
            "https://evil-sapa.c-nexco.co.jp/sapa?sapainfoid=17",
            "https://www.driveplaza.com/sapa/1/1/1/",
            "https://c-nexco.co.jp/sapa?sapainfoid=17",
        ],
    )
    def test_URL帰属判定の検証_別ホストまたは類似ホストのURLだった場合_Falseが返る(self, url: str) -> None:
        assert CentralSite().owns_url(url) is False


class Test一覧URL構成:
    def test_一覧URL構成の検証_中日本管内の都道府県のみ指定された場合_検索結果URLのみ返る(self) -> None:
        urls = CentralSite().listing_urls((find_prefecture("23"),))  # 愛知県

        assert urls == (_SEARCH_RESULT_URL,)

    def test_一覧URL構成の検証_中日本管内以外の都道府県のみ指定された場合_空タプルが返る(self) -> None:
        urls = CentralSite().listing_urls((find_prefecture("01"),))  # 北海道

        assert urls == ()

    def test_一覧URL構成の検証_中日本管内と管内以外が混在する場合_検索結果URLが1件のみ返る(self) -> None:
        urls = CentralSite().listing_urls((find_prefecture("23"), find_prefecture("01")))

        assert urls == (_SEARCH_RESULT_URL,)

    def test_一覧URL構成の検証_都道府県が指定されない場合_空タプルが返る(self) -> None:
        urls = CentralSite().listing_urls(())

        assert urls == ()


class Test一覧パース:
    def test_一覧パースの検証_上り下りの一対のフィクスチャだった場合_2件のスタブが絶対URLで抽出される(self) -> None:
        page = parse_html(_FIXTURE_LISTING_PAGE1_HTML, url=_SEARCH_RESULT_URL)

        result = CentralSite().parse_listing(page)

        assert isinstance(result, SapaListingResult)
        assert result.stubs == (
            SapaStub(display_name="港北PA（上り）", detail_url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=17"),
            SapaStub(display_name="港北PA（下り）", detail_url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=18"),
        )

    def test_一覧パースの検証_page_sp配下の重複データがあっても二重カウントされない(self) -> None:
        page = parse_html(_FIXTURE_LISTING_PAGE1_HTML, url=_SEARCH_RESULT_URL)

        result = CentralSite().parse_listing(page)

        # page_sp側にも同一の2件が重複配置されているが、div#page配下のみを
        # 対象とするため、抽出結果は2件のままである。
        assert len(result.stubs) == 2

    def test_一覧パースの検証_リンクを欠くリンクなし要素だった場合_スキップされskipped_countが増える(self) -> None:
        page = parse_html(_FIXTURE_LISTING_PAGE1_HTML, url=_SEARCH_RESULT_URL)

        result = CentralSite().parse_listing(page)

        # 「名称不明PA（上り）」(href欠落)と、名称が空の要素(sapainfoid=99)の
        # 2件がスキップされる。
        assert result.skipped_count == 2

    def test_一覧パースの検証_名称が空だがURLは解釈できた要素だった場合_listed_urlsには残るがstub化されない(
        self,
    ) -> None:
        page = parse_html(_FIXTURE_LISTING_PAGE1_HTML, url=_SEARCH_RESULT_URL)

        result = CentralSite().parse_listing(page)

        assert "https://sapa.c-nexco.co.jp/sapa?sapainfoid=99" in result.listed_urls
        assert all(stub.detail_url != "https://sapa.c-nexco.co.jp/sapa?sapainfoid=99" for stub in result.stubs)

    def test_一覧パースの検証_上りと下りは別のスタブとして扱われる(self) -> None:
        page = parse_html(_FIXTURE_LISTING_PAGE1_HTML, url=_SEARCH_RESULT_URL)

        result = CentralSite().parse_listing(page)

        up_stub, down_stub = result.stubs
        assert up_stub != down_stub
        assert up_stub.detail_url != down_stub.detail_url
        assert up_stub.display_name != down_stub.display_name

    def test_一覧パースの検証_tableTr要素が0件の場合_空のスタブと空のlisted_urlsが返る(self) -> None:
        page = parse_html(_FIXTURE_LISTING_HTML_NO_ELEMENTS, url=_SEARCH_RESULT_URL)

        result = CentralSite().parse_listing(page)

        assert result.stubs == ()
        assert result.listed_urls == frozenset()
        assert result.skipped_count == 0


class Testページネーションを跨いだ一覧パースのページ非依存性:
    """listing_urls自体は1ページ目のみを返す既知の制限があるため(central.pyの
    モジュールdocstring参照)、本クラスは``parse_listing``単体が「どのページの
    HTMLを渡されても正しくパースできる(ページ非依存)」ことのみを、2つの
    独立したフィクスチャページを個別にパースし結果を結合することで証明する。
    実際の複数ページ取得(collectorによる``listing_urls``の反復呼び出し)は
    本テストの対象外である。
    """

    def test_一覧パースの検証_1ページ目と2ページ目を個別にパースし結合した場合_4件のスタブに正しく集約される(
        self,
    ) -> None:
        page1 = parse_html(_FIXTURE_LISTING_PAGE1_HTML, url=_SEARCH_RESULT_URL)
        page2 = parse_html(_FIXTURE_LISTING_PAGE2_HTML, url=f"{_SEARCH_RESULT_URL}?PageNum=2")

        site = CentralSite()
        result1 = site.parse_listing(page1)
        result2 = site.parse_listing(page2)

        # collectorが将来行うであろう集約(スタブの連結・listed_urlsの和集合・
        # skipped_countの合算)を模擬する。
        combined_stubs = result1.stubs + result2.stubs
        combined_listed_urls = result1.listed_urls | result2.listed_urls
        combined_skipped_count = result1.skipped_count + result2.skipped_count

        assert len(combined_stubs) == 4
        assert combined_stubs[-2:] == (
            SapaStub(
                display_name="EXPASA海老名（上り）",
                detail_url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=200",
            ),
            SapaStub(
                display_name="EXPASA海老名（下り）",
                detail_url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=201",
            ),
        )
        assert combined_listed_urls >= {
            "https://sapa.c-nexco.co.jp/sapa?sapainfoid=17",
            "https://sapa.c-nexco.co.jp/sapa?sapainfoid=18",
            "https://sapa.c-nexco.co.jp/sapa?sapainfoid=200",
            "https://sapa.c-nexco.co.jp/sapa?sapainfoid=201",
        }
        assert combined_skipped_count == result1.skipped_count + result2.skipped_count == 2


class Test詳細抽出:
    def test_詳細抽出の検証_港北PA上りフィクスチャだった場合_名称路線名方向方面住所駐車場座標が正しく抽出される(
        self,
    ) -> None:
        page = parse_html(_build_detail_html(), url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=17")

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert isinstance(detail, SapaDetail)
        assert detail.name == "港北PA"
        assert detail.road_name == "東名高速道路"
        assert detail.direction is Direction.UP
        assert detail.area_direction == "東京方面"
        assert detail.address == "神奈川県横浜市緑区"
        assert detail.postal_code is None
        assert detail.parking == Parking(large=25, standard=68, disabled=None)
        assert detail.coordinate is not None
        assert detail.coordinate.latitude == pytest.approx(35.53287)
        assert detail.coordinate.longitude == pytest.approx(139.526834)
        assert detail.tel is None
        assert detail.opening_hours is None
        assert detail.websites == ()
        assert detail.facilities == ()

    def test_詳細抽出の検証_下りフィクスチャだった場合_directionが下りで方面も異なる(self) -> None:
        page = parse_html(
            _build_detail_html(
                direction_label="下り",
                area_direction="名古屋方面",
                map_href=(
                    "https://www.google.com/maps/place/EXPASA/@35.4319454,139.3987988,17z/data=!3m1!4b1?entry=ttu"
                ),
            ),
            url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=18",
        )

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert detail.direction is Direction.DOWN
        assert detail.area_direction == "名古屋方面"
        assert detail.coordinate.latitude == pytest.approx(35.4319454)
        assert detail.coordinate.longitude == pytest.approx(139.3987988)

    def test_詳細抽出の検証_異なる施設の上りと下りは別データになる(self) -> None:
        up_page = parse_html(_build_detail_html(direction_label="上り"), url="https://sapa.c-nexco.co.jp/x/1")
        down_page = parse_html(_build_detail_html(direction_label="下り"), url="https://sapa.c-nexco.co.jp/x/2")

        up_detail = CentralSite().extract_detail(up_page, detail_url=up_page.url)
        down_detail = CentralSite().extract_detail(down_page, detail_url=down_page.url)

        assert up_detail != down_detail
        assert up_detail.direction is Direction.UP
        assert down_detail.direction is Direction.DOWN

    def test_詳細抽出の検証_Googleマップリンクが存在しない場合_coordinateはNoneで例外は送出されない(self) -> None:
        page = parse_html(_build_detail_html(map_href=None), url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=17")

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert detail.coordinate is None

    def test_詳細抽出の検証_Googleマップリンクが座標形式に一致しない場合_coordinateはNoneで例外は送出されない(
        self,
    ) -> None:
        page = parse_html(
            _build_detail_html(map_href="https://www.google.com/maps/place/no-coords-here"),
            url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=17",
        )

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert detail.coordinate is None

    def test_詳細抽出の検証_上下集約施設で見出しに方向表記が無い場合_directionと方面はNoneになる(self) -> None:
        html = """
<html>
  <body>
    <div class="mod-box-inset sapa_summary">
      <p><span>C1</span> 集約テスト線</p>
      <h3 class="heading">集約施設</h3>
      <p class="address">テスト県テスト市1-1</p>
    </div>
  </body>
</html>
"""
        page = parse_html(html, url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=500")

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert detail.name == "集約施設"
        assert detail.direction is None
        assert detail.area_direction is None

    def test_詳細抽出の検証_見出しが方面なしの単純な上り表記だった場合_共通ヘルパで方向が正しく解決され名称も除去される(
        self,
    ) -> None:
        # 方面・コロンを伴わない単純な2要素表記「港北PA（上り）」。3要素の複合
        # 正規表現には一致しないため、共通ヘルパ(normalize_direction/
        # strip_direction_notation)へのフォールバックで解決されることを検証する
        # (レビュー指摘: このフォールバックが無いと方向がNoneに落ち、生の
        # 「（上り）」表記がnameに残ってしまっていた)。
        html = """
<html>
  <body>
    <div class="mod-box-inset sapa_summary">
      <p><span>E1</span> 東名高速道路</p>
      <h3 class="heading">港北PA（上り）</h3>
      <p class="address">神奈川県横浜市緑区</p>
    </div>
  </body>
</html>
"""
        page = parse_html(html, url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=501")

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert detail.name == "港北PA"
        assert detail.direction is Direction.UP
        assert detail.area_direction is None

    def test_詳細抽出の検証_見出しが方面なしの単純な下り表記だった場合_共通ヘルパで方向が正しく解決され名称も除去される(
        self,
    ) -> None:
        html = """
<html>
  <body>
    <div class="mod-box-inset sapa_summary">
      <p><span>E1</span> 東名高速道路</p>
      <h3 class="heading">港北PA（下り）</h3>
      <p class="address">神奈川県横浜市緑区</p>
    </div>
  </body>
</html>
"""
        page = parse_html(html, url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=502")

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert detail.name == "港北PA"
        assert detail.direction is Direction.DOWN
        assert detail.area_direction is None

    def test_詳細抽出の検証_駐車場テキストに小型のみ含まれる場合_大型はNoneで小型のみ抽出される(self) -> None:
        page = parse_html(
            _build_detail_html(parking_text="小型：68（大型との兼用を含む）"),
            url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=17",
        )

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert detail.parking == Parking(large=None, standard=68, disabled=None)

    def test_詳細抽出の検証_住所と駐車場が丸ごと欠落する場合_該当項目のみNoneになる(self) -> None:
        html = """
<html>
  <body>
    <div class="mod-box-inset sapa_summary">
      <p><span>E1</span> 東名高速道路</p>
      <h3 class="heading">最小構成PA（上り：東京方面）</h3>
    </div>
  </body>
</html>
"""
        page = parse_html(html, url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=600")

        detail = CentralSite().extract_detail(page, detail_url=page.url)

        assert detail.name == "最小構成PA"
        assert detail.address is None
        assert detail.postal_code is None
        assert detail.parking is None
        assert detail.coordinate is None


class Test構造変化の検知:
    def test_詳細抽出の検証_見出しから名称を取得できない場合_StructureChangedErrorが送出される(self) -> None:
        page = parse_html(_FIXTURE_NO_HEADING_HTML, url="https://sapa.c-nexco.co.jp/sapa?sapainfoid=17")

        with pytest.raises(StructureChangedError):
            CentralSite().extract_detail(page, detail_url=page.url)
