import pytest

from roadstop_scraper.scraping import (
    ContentParseError,
    FetchFailedError,
    ScrapingEngineError,
    StructureChangedError,
)

_URL = "https://example.com/facilities/1"


def test_例外階層の検証_FetchFailedErrorが_送出された場合_基底例外として捕捉できる():
    # 取得失敗の専用例外が基底ScrapingEngineErrorとして捕捉できることを確認する
    with pytest.raises(ScrapingEngineError):
        raise FetchFailedError(_URL, 404, 1)


def test_例外階層の検証_ContentParseErrorが_送出された場合_基底例外として捕捉できる():
    # パース不能コンテンツの専用例外が基底ScrapingEngineErrorとして捕捉できることを確認する
    with pytest.raises(ScrapingEngineError):
        raise ContentParseError(_URL)


def test_例外階層の検証_StructureChangedErrorが_送出された場合_基底例外として捕捉できる():
    # HTML構造変化の専用例外が基底ScrapingEngineErrorとして捕捉できることを確認する
    with pytest.raises(ScrapingEngineError):
        raise StructureChangedError(_URL, ".facility-name")


def test_属性保持の検証_FetchFailedErrorが_ステータスコード付きで構築された場合_url_status_code_attemptsを保持する():
    # 呼び出し側が対象URL・ステータスコード・試行回数を参照できることを確認する
    error = FetchFailedError(_URL, 503, 3)

    assert error.url == _URL
    assert error.status_code == 503
    assert error.attempts == 3


def test_属性保持の検証_FetchFailedErrorが_通信エラーで構築された場合_status_codeはNoneを保持する():
    # タイムアウト・接続エラー等ステータスコードが得られない失敗ではNoneが保持されることを確認する
    error = FetchFailedError(_URL, None, 3)

    assert error.status_code is None


def test_メッセージ内容の検証_FetchFailedErrorが_構築された場合_メッセージに対象URLとステータスコードを含む():
    # 例外メッセージが日本語で対象URL・ステータスコードという文脈を含むことを確認する
    error = FetchFailedError(_URL, 404, 2)

    message = str(error)
    assert _URL in message
    assert "404" in message


def test_属性保持の検証_ContentParseErrorが_構築された場合_urlを保持する():
    # 呼び出し側が対象URLを参照できることを確認する
    error = ContentParseError(_URL)

    assert error.url == _URL


def test_メッセージ内容の検証_ContentParseErrorが_構築された場合_メッセージに対象URLを含む():
    # 例外メッセージが日本語で対象URLという文脈を含むことを確認する
    error = ContentParseError(_URL)

    assert _URL in str(error)


def test_属性保持の検証_StructureChangedErrorが_構築された場合_url_selectorを保持する():
    # 呼び出し側が対象URL・取得できなかった要素のセレクタを参照できることを確認する
    error = StructureChangedError(_URL, ".facility-name")

    assert error.url == _URL
    assert error.selector == ".facility-name"


def test_メッセージ内容の検証_StructureChangedErrorが_構築された場合_メッセージに対象URLとセレクタを含む():
    # 例外メッセージが日本語で対象URL・セレクタという文脈を含むことを確認する
    error = StructureChangedError(_URL, ".facility-name")

    message = str(error)
    assert _URL in message
    assert ".facility-name" in message


def test_例外階層の検証_ScrapingEngineErrorが_直接送出された場合_Exceptionとして捕捉できる():
    # 基底例外自体が標準のExceptionのサブタイプであることを確認する
    with pytest.raises(Exception):  # noqa: B017 - 基底型としての捕捉可否そのものを検証する
        raise ScrapingEngineError("エンジン全体の失敗")
