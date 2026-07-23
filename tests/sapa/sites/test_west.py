"""NEXCO西日本(w-holdings.co.jp)サイトアダプタ(west)の検証(タスク3.3)。

一覧が他2サイトと異なりJSONエンドポイント(``sapa/json/map-search.json``)から
供給される点(``listing_kind = "json"``)を踏まえ、``parse_listing``は
``HtmlPage``ではなく素の``list[dict]``(JSON配列)を直接受け取ることを検証する。
詳細ページの検証は実測(美山パーキングエリア・吉和サービスエリア)に基づく
フィクスチャHTMLで行う。実サイトへのライブHTTPアクセスは行わない。
"""

from __future__ import annotations

import pytest

from roadstop_scraper.geojson import Direction, Parking, find_prefecture
from roadstop_scraper.sapa.sites import SapaDetail, SapaListingResult, SapaStub
from roadstop_scraper.sapa.sites.west import WestSite
from roadstop_scraper.scraping import StructureChangedError, parse_html

_LISTING_JSON_URL = "https://www.w-holdings.co.jp/sapa/json/map-search.json"

# 実測(research.md、美山パーキングエリア・吉和サービスエリア)を模した一覧
# JSONフィクスチャ。上り・下りは別レコード(別id)として供給される。
_FIXTURE_LISTING_RECORDS: list[dict[str, object]] = [
    {
        "id": "30020",
        "sa_pa_short": "美山PA（下）",
        "url": "https://www.w-holdings.co.jp/sapa/30020/",
        "road_name": "南九州西回り自動車道",
        "up_down_line": "down",
    },
    {
        "id": "30010",
        "sa_pa_short": "美山PA（上）",
        "url": "https://www.w-holdings.co.jp/sapa/30010/",
        "road_name": "南九州西回り自動車道",
        "up_down_line": "up",
    },
    {
        # sa_pa_short欠落: URLは解釈できるためlisted_urlsには残るがstub化されない。
        "id": "99999",
        "url": "https://www.w-holdings.co.jp/sapa/99999/",
        "road_name": "テスト線",
    },
    {
        # url欠落: 名称はあるがURLが取れないためstub化もlisted_urls追加もされない。
        "id": "88888",
        "sa_pa_short": "名称のみPA",
        "url": "",
    },
]


def _build_detail_html(
    *,
    name: str = "美山パーキングエリア",
    furigana: str = "みやま",
    road_name: str = "南九州西回り自動車道",
    active_direction_label: str = "下り",
    active_area_direction: str = "鹿児島方面",
    opposite_direction_label: str = "上り",
    opposite_area_direction: str = "いちき串木野方面",
    address: str = "鹿児島県日置市東市来町美山1878-5",
    parking_text: str = (
        "【大型】5 【小型】10 【兼用】0 【二輪】4 【トレーラー】1 【障がい者用大型】0 【障がい者用小型】1"
    ),
) -> str:
    # research.md/タスク3.3実測(美山PA下り)を模したフィクスチャ。
    return f"""
<html>
  <head><title>{name}（{active_direction_label}）｜NEXCO西日本のSA・PA情報サイト</title></head>
  <body>
    <p class="p-sapa-heading-02__lead">{road_name}</p>
    <h1 class="p-sapa-heading-02__title ttl-heading-01"><ruby>{name}<rt>{furigana}</rt></ruby></h1>
    <span class="p-sapa-area-tag__tag box-tag-02">{opposite_direction_label}</span>
    <p class="p-sapa-area-tag__text">{opposite_area_direction}</p>
    <div class="p-sapa-area-tag__tag box-tag-02 box-tag-02_active">{active_direction_label}</div>
    <p class="p-sapa-area-tag__text p-sapa-area-tag__text_active">{active_area_direction}</p>
    <div class="box-facility-info">
      <ul class="box-facility-info__list">
        <li>
          <p class="box-facility-info__list-head">住所</p>
          <p class="box-facility-info__list-text"><p>{address}</p></p>
        </li>
        <li>
          <p class="box-facility-info__list-head">パーキング</p>
          <p class="box-facility-info__list-text">{parking_text}</p>
        </li>
      </ul>
    </div>
  </body>
</html>
"""


_FIXTURE_NO_NAME_HTML = """
<html>
  <body>
    <p class="p-sapa-heading-02__lead">構造テスト線</p>
    <div class="box-facility-info">
      <ul class="box-facility-info__list">
        <li>
          <p class="box-facility-info__list-head">住所</p>
          <p class="box-facility-info__list-text"><p>テスト県テスト市1-1</p></p>
        </li>
      </ul>
    </div>
  </body>
</html>
"""


class TestListingKind:
    def test_ListingKindの検証_westアダプタだった場合_jsonになる(self) -> None:
        assert WestSite().listing_kind == "json"


class TestURL帰属判定:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.w-holdings.co.jp/sapa/30020/",
            "http://w-holdings.co.jp/sapa/json/map-search.json",
        ],
    )
    def test_URL帰属判定の検証_w_holdings_co_jpのホストだった場合_Trueが返る(self, url: str) -> None:
        assert WestSite().owns_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://w-holdings.co.jp.evil.example/sapa/1/",
            "https://evil-w-holdings.co.jp/sapa/1/",
            "https://www.driveplaza.com/sapa/1/1/1/",
            "https://sapa.c-nexco.co.jp/sapa?sapainfoid=1",
        ],
    )
    def test_URL帰属判定の検証_別ホストまたは類似ホストのURLだった場合_Falseが返る(self, url: str) -> None:
        assert WestSite().owns_url(url) is False


class Test一覧URL構成:
    def test_一覧URL構成の検証_西日本管内の都道府県のみ指定された場合_JSONエンドポイントのURLのみ返る(self) -> None:
        urls = WestSite().listing_urls((find_prefecture("40"),))  # 福岡県

        assert urls == (_LISTING_JSON_URL,)

    def test_一覧URL構成の検証_西日本管内以外の都道府県のみ指定された場合_空タプルが返る(self) -> None:
        urls = WestSite().listing_urls((find_prefecture("01"),))  # 北海道

        assert urls == ()

    def test_一覧URL構成の検証_西日本管内と管内以外が混在する場合_JSONエンドポイントのURLが1件のみ返る(self) -> None:
        urls = WestSite().listing_urls((find_prefecture("40"), find_prefecture("01")))

        assert urls == (_LISTING_JSON_URL,)

    def test_一覧URL構成の検証_都道府県が指定されない場合_空タプルが返る(self) -> None:
        urls = WestSite().listing_urls(())

        assert urls == ()


class Test一覧パース:
    def test_一覧パースの検証_上り下りの一対を含むJSON配列だった場合_2件のスタブが抽出される(self) -> None:
        result = WestSite().parse_listing(_FIXTURE_LISTING_RECORDS)

        assert isinstance(result, SapaListingResult)
        assert result.stubs == (
            SapaStub(display_name="美山PA（下）", detail_url="https://www.w-holdings.co.jp/sapa/30020/"),
            SapaStub(display_name="美山PA（上）", detail_url="https://www.w-holdings.co.jp/sapa/30010/"),
        )

    def test_一覧パースの検証_detail_urlは絶対URLのままas_isで使われる(self) -> None:
        result = WestSite().parse_listing(_FIXTURE_LISTING_RECORDS)

        assert all(stub.detail_url.startswith("https://www.w-holdings.co.jp/") for stub in result.stubs)

    def test_一覧パースの検証_上りと下りは別のスタブとして扱われる(self) -> None:
        result = WestSite().parse_listing(_FIXTURE_LISTING_RECORDS)

        down_stub, up_stub = result.stubs
        assert down_stub != up_stub
        assert down_stub.detail_url != up_stub.detail_url
        assert down_stub.display_name != up_stub.display_name

    def test_一覧パースの検証_sa_pa_short欠落レコードだった場合_スキップされるがurlはlisted_urlsに残る(self) -> None:
        result = WestSite().parse_listing(_FIXTURE_LISTING_RECORDS)

        assert "https://www.w-holdings.co.jp/sapa/99999/" in result.listed_urls
        assert all(stub.detail_url != "https://www.w-holdings.co.jp/sapa/99999/" for stub in result.stubs)

    def test_一覧パースの検証_url空文字レコードだった場合_listed_urlsにもstubsにも含まれずスキップされる(
        self,
    ) -> None:
        result = WestSite().parse_listing(_FIXTURE_LISTING_RECORDS)

        assert all(stub.display_name != "名称のみPA" for stub in result.stubs)
        assert "" not in result.listed_urls

    def test_一覧パースの検証_不正レコードが2件含まれる場合_skipped_countが2になる(self) -> None:
        result = WestSite().parse_listing(_FIXTURE_LISTING_RECORDS)

        assert result.skipped_count == 2

    def test_一覧パースの検証_contentが空リストの場合_空のスタブと空のlisted_urlsが返る(self) -> None:
        result = WestSite().parse_listing([])

        assert result.stubs == ()
        assert result.listed_urls == frozenset()
        assert result.skipped_count == 0

    def test_一覧パースの検証_contentがリストでない場合_例外を送出せず0件として扱われる(self) -> None:
        result = WestSite().parse_listing({"unexpected": "shape"})

        assert isinstance(result, SapaListingResult)
        assert result.stubs == ()
        assert result.skipped_count == 0

    def test_一覧パースの検証_contentがNoneの場合_例外を送出せず0件として扱われる(self) -> None:
        result = WestSite().parse_listing(None)

        assert result.stubs == ()

    def test_一覧パースの検証_リスト内に辞書でない要素が混在する場合_その要素はスキップされ例外は送出されない(
        self,
    ) -> None:
        records: list[object] = [
            {"sa_pa_short": "正常PA", "url": "https://www.w-holdings.co.jp/sapa/1/"},
            "unexpected-string-element",
            123,
            None,
        ]

        result = WestSite().parse_listing(records)

        assert result.stubs == (SapaStub(display_name="正常PA", detail_url="https://www.w-holdings.co.jp/sapa/1/"),)
        assert result.skipped_count == 3


class Test詳細抽出:
    def test_詳細抽出の検証_美山PA下りフィクスチャだった場合_名称路線名方向方面住所駐車場が正しく抽出される(
        self,
    ) -> None:
        page = parse_html(_build_detail_html(), url="https://www.w-holdings.co.jp/sapa/30020/")

        detail = WestSite().extract_detail(page, detail_url=page.url)

        assert isinstance(detail, SapaDetail)
        assert detail.name == "美山パーキングエリア"
        assert detail.road_name == "南九州西回り自動車道"
        assert detail.direction is Direction.DOWN
        assert detail.area_direction == "鹿児島方面"
        assert detail.address == "鹿児島県日置市東市来町美山1878-5"
        assert detail.postal_code is None
        assert detail.parking == Parking(large=5, standard=10, disabled=None)
        assert detail.coordinate is None
        assert detail.tel is None
        assert detail.opening_hours is None
        assert detail.websites == ()
        assert detail.facilities == ()

    def test_詳細抽出の検証_美山PA上りフィクスチャだった場合_directionと方面が下りと異なる(self) -> None:
        page = parse_html(
            _build_detail_html(
                active_direction_label="上り",
                active_area_direction="いちき串木野方面",
                opposite_direction_label="下り",
                opposite_area_direction="鹿児島方面",
            ),
            url="https://www.w-holdings.co.jp/sapa/30010/",
        )

        detail = WestSite().extract_detail(page, detail_url=page.url)

        assert detail.direction is Direction.UP
        assert detail.area_direction == "いちき串木野方面"

    def test_詳細抽出の検証_ふりがなは名称から除去され施設名のみが抽出される(self) -> None:
        page = parse_html(_build_detail_html(name="美山パーキングエリア", furigana="みやま"), url="x")

        detail = WestSite().extract_detail(page, detail_url="x")

        assert detail.name == "美山パーキングエリア"
        assert "みやま" not in detail.name

    def test_詳細抽出の検証_吉和SAフィクスチャだった場合_名称路線名駐車場のセレクタが同様に一般化する(self) -> None:
        page = parse_html(
            _build_detail_html(
                name="吉和サービスエリア",
                furigana="よしわ",
                road_name="中国自動車道",
                address="広島県廿日市市吉和",
                parking_text="【大型】20 【小型】50 【兼用】0",
            ),
            url="https://www.w-holdings.co.jp/sapa/09440/",
        )

        detail = WestSite().extract_detail(page, detail_url=page.url)

        assert detail.name == "吉和サービスエリア"
        assert detail.road_name == "中国自動車道"
        assert detail.parking == Parking(large=20, standard=50, disabled=None)

    def test_詳細抽出の検証_美山PAと吉和SAでふりがなの実値が異なることを確認する(self) -> None:
        miyama_page = parse_html(_build_detail_html(name="美山パーキングエリア", furigana="みやま"), url="x")
        yoshiwa_page = parse_html(
            _build_detail_html(name="吉和サービスエリア", furigana="よしわ", road_name="中国自動車道"),
            url="y",
        )

        miyama_detail = WestSite().extract_detail(miyama_page, detail_url="x")
        yoshiwa_detail = WestSite().extract_detail(yoshiwa_page, detail_url="y")

        assert miyama_detail.name != yoshiwa_detail.name
        assert miyama_detail != yoshiwa_detail

    def test_詳細抽出の検証_駐車場テキストに大型のみ含まれる場合_小型はNoneで大型のみ抽出される(self) -> None:
        page = parse_html(_build_detail_html(parking_text="【大型】5 【兼用】0"), url="x")

        detail = WestSite().extract_detail(page, detail_url="x")

        assert detail.parking == Parking(large=5, standard=None, disabled=None)

    def test_詳細抽出の検証_住所が丸ごと欠落する場合_addressとpostal_codeのみNoneになる(self) -> None:
        html = """
<html>
  <body>
    <p class="p-sapa-heading-02__lead">南九州西回り自動車道</p>
    <h1 class="p-sapa-heading-02__title ttl-heading-01"><ruby>最小構成PA<rt>さいしょう</rt></ruby></h1>
    <div class="p-sapa-area-tag__tag box-tag-02 box-tag-02_active">下り</div>
    <p class="p-sapa-area-tag__text p-sapa-area-tag__text_active">鹿児島方面</p>
  </body>
</html>
"""
        page = parse_html(html, url="x")

        detail = WestSite().extract_detail(page, detail_url="x")

        assert detail.name == "最小構成PA"
        assert detail.address is None
        assert detail.postal_code is None
        assert detail.parking is None


class Test上り下りは別データとして扱われる:
    def test_詳細抽出の検証_同一施設の上りと下りのフィクスチャだった場合_directionが異なり別データになる(
        self,
    ) -> None:
        down_page = parse_html(_build_detail_html(active_direction_label="下り"), url="https://x/1")
        up_page = parse_html(
            _build_detail_html(
                active_direction_label="上り",
                active_area_direction="いちき串木野方面",
                opposite_direction_label="下り",
                opposite_area_direction="鹿児島方面",
            ),
            url="https://x/2",
        )

        down_detail = WestSite().extract_detail(down_page, detail_url="https://x/1")
        up_detail = WestSite().extract_detail(up_page, detail_url="https://x/2")

        assert down_detail != up_detail
        assert down_detail.direction is Direction.DOWN
        assert up_detail.direction is Direction.UP


class Test構造変化の検知:
    def test_詳細抽出の検証_名称を取得できない場合_StructureChangedErrorが送出される(self) -> None:
        page = parse_html(_FIXTURE_NO_NAME_HTML, url="https://www.w-holdings.co.jp/sapa/0/")

        with pytest.raises(StructureChangedError):
            WestSite().extract_detail(page, detail_url=page.url)
