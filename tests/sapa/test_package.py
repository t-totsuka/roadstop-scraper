"""sapaパッケージ雛形の疎通確認(タスク1.2)。

design.md「File Structure Plan」で定義されたディレクトリ構成のとおりに
新設パッケージが作成され、importが成功することを確認する。実際の機能
テスト(サイトアダプタ・収集ループ等)は後続タスク(2.x〜5.x)で追加する。
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
