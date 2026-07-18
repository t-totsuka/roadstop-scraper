import roadstop_scraper.michinoeki


def test_michinoekiパッケージの検証_importした場合_成功する():
    assert roadstop_scraper.michinoeki is not None


def test_michinoekiパッケージの検証_公開APIを確認した場合_主要な公開シンボルが再公開されている():
    # design.md「Architecture」節: geojson/・scraping/と同様、michinoekiも
    # __init__.pyで公開APIを集約する。利用側が実際に使う主要な型・関数が
    # __all__に列挙され、モジュール属性としてimportできることを確認する。
    expected = {
        "REGIONS",
        "InvalidScopeError",
        "ListingResult",
        "ListingUnavailableError",
        "MergeResult",
        "PrefectureRunResult",
        "ScopeSpec",
        "StationStub",
        "extract_station_properties",
        "fetch_station_stubs",
        "main",
        "merge_with_previous",
        "resolve_scope",
        "run_prefecture",
        "run_scope",
    }
    assert set(roadstop_scraper.michinoeki.__all__) == expected
    for name in expected:
        assert hasattr(roadstop_scraper.michinoeki, name)


def test_michinoekiパッケージの検証_公開APIを確認した場合_site_urlsのシンボルは再公開されない():
    # site_urls(SITE_PREFECTURE_CODES・build_search_url)は対象サイト固有の
    # URL構築の内部実装詳細であり、design.mdのBoundary Commitmentsに基づき
    # 公開APIには含めない。
    assert "SITE_PREFECTURE_CODES" not in roadstop_scraper.michinoeki.__all__
    assert "build_search_url" not in roadstop_scraper.michinoeki.__all__
