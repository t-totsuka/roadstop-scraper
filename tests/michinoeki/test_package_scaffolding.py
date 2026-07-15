import roadstop_scraper.michinoeki


def test_michinoekiパッケージの検証_importした場合_成功する():
    assert roadstop_scraper.michinoeki is not None


def test_michinoekiパッケージの検証_公開APIを確認した場合_空リストである():
    assert roadstop_scraper.michinoeki.__all__ == []
