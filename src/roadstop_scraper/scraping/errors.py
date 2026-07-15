"""スクレイピングエンジン(04-scraping-engine)の共通例外階層。

エンジンの全失敗モードは :class:`ScrapingEngineError` のサブタイプとして正規化
される。05/06の利用側は基底例外を捕捉すれば全失敗を一様に扱えるほか、
サブタイプで捕捉して障害種別(取得失敗・パース不能・構造変化)ごとに
継続/中断を選択できる。依存方向の最左に位置し、他モジュールへは依存しない。
"""

from __future__ import annotations

__all__ = [
    "ContentParseError",
    "FetchFailedError",
    "ScrapingEngineError",
    "StructureChangedError",
]


class ScrapingEngineError(Exception):
    """エンジンの基底例外。05/06はこれを捕捉すれば全失敗を扱える。"""


class FetchFailedError(ScrapingEngineError):
    """HTTP取得の最終失敗(1.5、2.6)。

    :attr:`url` に対象URL、:attr:`status_code` に応答ステータスコード
    (タイムアウト・接続エラー等の通信エラー時は ``None``)、:attr:`attempts`
    に試行回数(リトライ含む)を保持する。
    """

    def __init__(self, url: str, status_code: int | None, attempts: int) -> None:
        self.url = url
        self.status_code = status_code
        self.attempts = attempts
        super().__init__(f"URL '{url}' の取得に失敗しました(status_code={status_code}, attempts={attempts})")


class ContentParseError(ScrapingEngineError):
    """パース不能な不正コンテンツ(3.4)。

    :attr:`url` に対象URLを保持する。
    """

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"URL '{url}' のコンテンツをパースできませんでした")


class StructureChangedError(ScrapingEngineError):
    """HTML構造変化の検知(4.1、4.2)。

    対象サイトのHTML構造が変化し、抽出必須の要素が取得できなかった場合に
    送出される。:attr:`url` に対象URL、:attr:`selector` に取得できなかった
    要素のセレクタを保持する。利用側はこの型を独立して捕捉することで、
    一時的な取得失敗(:class:`FetchFailedError`)と区別し、抽出ルールの
    修正が必要な事態として処理の継続/中断を選択できる(4.4)。
    """

    def __init__(self, url: str, selector: str) -> None:
        self.url = url
        self.selector = selector
        super().__init__(
            f"URL '{url}' でセレクタ '{selector}' に対応する要素が見つかりません(HTML構造が変化した可能性があります)"
        )
