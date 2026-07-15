"""取得(PageFetcher)→解析(parse_html/HtmlPage)→レコード生成(extract_record)の結合検証。

タスク3.1の観測可能な完了条件を検証する: 偽セッション(HTTP層のみをスタブ化)と
実ファイル相当のフィクスチャHTMLを用いて、fetch_text→parse_html→extract_recordの
一連の流れを実際のコンポーネントのまま(モックせず)通し、取得元URLが対応付けられた
構造化レコード(``ExtractedRecord``)が得られることを証明する(design.md「Integration
Tests」、要件1.1・3.1・6.1・6.2)。HTTP層のスタブ化は``SessionLike``を満たす偽セッション
の注入で行う(test_fetcher.pyと同じ方式。追加のモックライブラリは導入しない)。
"""

from __future__ import annotations

from roadstop_scraper.scraping.config import ScrapingConfig
from roadstop_scraper.scraping.extract import ExtractedRecord, FieldSpec, extract_record
from roadstop_scraper.scraping.fetcher import PageFetcher
from roadstop_scraper.scraping.parser import parse_html

# 実際の道の駅サイトの施設一覧ページを模した、CSSセレクタで抽出可能な構造を持つ
# フィクスチャHTML(単一タグの最小文字列ではなく、名称・住所・電話番号・公式サイト
# リンクを持つ小規模な施設情報ブロックとする)。
_FIXTURE_HTML = """
<html>
  <body>
    <header>ナビゲーション等ここでは無視される要素</header>
    <main>
      <article class="facility">
        <h1 class="facility-name">  道の駅 スクレイピング湖畔  </h1>
        <p class="address">北海道札幌市中央区北一条西二丁目1-1</p>
        <p class="tel">011-123-4567</p>
        <a class="official-link" href="  https://example.com/roadstop/lakeside  ">公式サイト</a>
      </article>
    </main>
  </body>
</html>
"""


class _FakeResponse:
    """``ResponseLike``を満たす偽レスポンス(test_fetcher.pyと同じ形)。"""

    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.apparent_encoding = "utf-8"


class _FakeSession:
    """HTTP層のみをスタブ化する偽セッション。事前登録した応答を返す(test_fetcher.pyと同じ形)。"""

    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[str] = []

    def get(self, url, *, timeout, headers):
        self.calls.append(url)
        return self._response


class _FakeRateLimiter:
    """試験を高速化するため、待機せず呼び出し回数のみ記録する偽RateLimiter。"""

    def __init__(self) -> None:
        self.wait_count = 0

    def wait(self) -> None:
        self.wait_count += 1


def _fast_config() -> ScrapingConfig:
    return ScrapingConfig(
        timeout_seconds=5.0,
        max_retries=0,
        retry_wait_seconds=0.0,
        min_request_interval_seconds=0.0,
    )


def test_結合検証_取得からレコード生成までの一連の流れが_成功した場合_構造化レコードが得られる():
    url = "https://example.com/roadstop/lakeside"
    response = _FakeResponse(
        200,
        _FIXTURE_HTML.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    session = _FakeSession(response)
    fetcher = PageFetcher(_fast_config(), rate_limiter=_FakeRateLimiter(), session=session)

    # 1. 取得: 偽セッション経由でHTTP層のみをスタブ化し、実際のPageFetcherでfetch_textを実行する
    fetched = fetcher.fetch_text(url)
    assert fetched.url == url
    assert session.calls == [url]

    # 2. 解析: 取得した本文を実際のparse_htmlに通し、HtmlPageを得る
    page = parse_html(fetched.text, fetched.url)

    # 3. レコード生成: 必須/任意・テキスト/属性が混在するFieldSpecでextract_recordを実行する
    specs = [
        FieldSpec(name="name", selector=".facility-name", required=True),
        FieldSpec(name="address", selector=".address", required=False),
        FieldSpec(name="tel", selector=".tel", required=False),
        FieldSpec(name="official_url", selector=".official-link", attribute="href", required=True),
        # フィクスチャに存在しない任意項目: 欠損としてNoneになることを併せて確認する
        FieldSpec(name="fax", selector=".fax", required=False),
    ]
    record = extract_record(page, specs)

    assert isinstance(record, ExtractedRecord)
    # 6.2: 抽出結果に取得元URL(source_url)が対応付けられている
    assert record.source_url == url
    # 6.1/6.3: 名称・住所・電話番号・公式サイトURLが構造化された値として得られ、
    # フィクスチャに存在しない任意項目はキーを保持したままNoneになる
    assert record.values == {
        "name": "道の駅 スクレイピング湖畔",
        "address": "北海道札幌市中央区北一条西二丁目1-1",
        "tel": "011-123-4567",
        "official_url": "https://example.com/roadstop/lakeside",
        "fax": None,
    }
