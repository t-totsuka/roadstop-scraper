"""sapaパッケージの疎通確認と公開APIの検証。

design.md「File Structure Plan」で定義されたディレクトリ構成のとおりに
パッケージが構成され、importが成功すること、および利用側が参照すべき
主要な公開シンボル(``run_scope``・``main``等)がパッケージ直下から
再公開されていること(``tests/michinoeki/test_package_scaffolding.py``と
同じ規約)を確認する。
"""

import roadstop_scraper.sapa
import roadstop_scraper.sapa.address
import roadstop_scraper.sapa.cli
import roadstop_scraper.sapa.collector
import roadstop_scraper.sapa.geocoding
import roadstop_scraper.sapa.runner
import roadstop_scraper.sapa.sites
import roadstop_scraper.sapa.sites.central
import roadstop_scraper.sapa.sites.east
import roadstop_scraper.sapa.sites.west


def test_sapaパッケージの検証_importした場合_成功する():
    assert roadstop_scraper.sapa is not None


def test_sapa公開APIの検証_主要シンボルがパッケージ直下から再公開されている():
    # 利用側が個別モジュールへ直接依存せずに済むよう、__all__に列挙され、
    # モジュール属性としてimportできることを確認する(michinoekiと同じ規約)。
    expected = {
        "SapaPrefectureResult",
        "SapaScopeRunResult",
        "main",
        "run_prefecture",
        "run_prefectures",
        "run_scope",
    }
    assert set(roadstop_scraper.sapa.__all__) == expected
    for name in expected:
        assert getattr(roadstop_scraper.sapa, name) is not None


def test_sapaサブモジュールの検証_importした場合_成功する():
    assert roadstop_scraper.sapa.sites is not None
    assert roadstop_scraper.sapa.sites.east is not None
    assert roadstop_scraper.sapa.sites.central is not None
    assert roadstop_scraper.sapa.sites.west is not None
    assert roadstop_scraper.sapa.address is not None
    assert roadstop_scraper.sapa.geocoding is not None
    assert roadstop_scraper.sapa.collector is not None
    assert roadstop_scraper.sapa.runner is not None
    assert roadstop_scraper.sapa.cli is not None
