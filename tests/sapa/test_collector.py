"""``sapa.collector.SapaPartialStore``(タスク4.1)の検証。

design.md「sapa.collector」State Managementのとおり、実行横断(サイト横断・
都道府県横断)の単一キー``"sapa-partial"``で部分結果(features・
skipped_counts・geocoded_counts)を``common.ResumeStore``へ逐次永続化する
クラスの振る舞いを検証する。05の``_PartialResultStore``(都道府県単位・
フラットなskipped_count)とは異なり、都道府県コード別(および都道府県不明の
"unknown"バケット)のカウントマップを保持する点が本タスクの主眼(5.3, 7.2)。

観測可能な完了条件:
- 追記→復元の往復で内容が一致すること(features/skipped_counts/geocoded_counts)
- 同一``source_url``の再追記が重複しないこと(冪等)
- ``clear()``後は同一インスタンス・新規インスタンスとも空から始まること
"""

from __future__ import annotations

from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.geojson import Coordinate, FacilityFeature, FacilityKind, FacilityProperties
from roadstop_scraper.sapa.collector import SapaPartialStore


def _feature(source_url: str, *, name: str = "テストSA", pref_code: str = "13") -> FacilityFeature:
    return FacilityFeature(
        coordinate=Coordinate(longitude=139.7, latitude=35.6),
        properties=FacilityProperties(
            name=name,
            kind=FacilityKind.SAPA,
            pref_code=pref_code,
            pref_name="東京都",
            source_url=source_url,
        ),
    )


def _make_store(tmp_path) -> ResumeStore:
    return ResumeStore(state_dir=tmp_path / ".resume")


def test_add_featureの検証_複数の異なるsource_urlを追加した場合_featuresへ全件反映される(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    partial_store.add_feature(_feature("https://example.com/a"))
    partial_store.add_feature(_feature("https://example.com/b"))

    urls = {f.properties.source_url for f in partial_store.features}
    assert urls == {"https://example.com/a", "https://example.com/b"}
    assert len(partial_store.features) == 2


def test_add_featureの検証_同一source_urlを再追加した場合_件数が増えず新しい内容へ置き換わる(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    partial_store.add_feature(_feature("https://example.com/a", name="旧名称"))
    partial_store.add_feature(_feature("https://example.com/a", name="新名称"))

    assert len(partial_store.features) == 1
    assert partial_store.features[0].properties.name == "新名称"


def test_add_skipの検証_複数の都道府県コードとnoneを追加した場合_コード別とunknownバケットへ集計される(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    partial_store.add_skip("13")
    partial_store.add_skip("13")
    partial_store.add_skip("01")
    partial_store.add_skip(None)

    assert partial_store.skipped_counts == {"13": 2, "01": 1, "unknown": 1}


def test_add_geocodedの検証_複数の都道府県コードを追加した場合_コード別に加算される(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    partial_store.add_geocoded("13")
    partial_store.add_geocoded("13")
    partial_store.add_geocoded("27")

    assert partial_store.geocoded_counts == {"13": 2, "27": 1}


def test_復元の検証_追記後に同じストアから新規構築した場合_features_skipped_counts_geocoded_countsが一致する(
    tmp_path,
):
    store = _make_store(tmp_path)
    partial_store = SapaPartialStore(store=store)

    partial_store.add_feature(_feature("https://example.com/a"))
    partial_store.add_feature(_feature("https://example.com/b"))
    partial_store.add_skip("13")
    partial_store.add_skip(None)
    partial_store.add_geocoded("13")

    restored = SapaPartialStore(store=store)

    assert {f.properties.source_url for f in restored.features} == {
        "https://example.com/a",
        "https://example.com/b",
    }
    assert restored.skipped_counts == {"13": 1, "unknown": 1}
    assert restored.geocoded_counts == {"13": 1}


def test_clearの検証_クリア後は同一インスタンスも新規構築したインスタンスも空から始まる(tmp_path):
    store = _make_store(tmp_path)
    partial_store = SapaPartialStore(store=store)

    partial_store.add_feature(_feature("https://example.com/a"))
    partial_store.add_skip("13")
    partial_store.add_geocoded("13")

    partial_store.clear()

    assert partial_store.features == []
    assert partial_store.skipped_counts == {}
    assert partial_store.geocoded_counts == {}

    restored = SapaPartialStore(store=store)
    assert restored.features == []
    assert restored.skipped_counts == {}
    assert restored.geocoded_counts == {}


def test_初期状態の検証_未保存のストアから構築した場合_空のfeatures_skipped_counts_geocoded_countsで開始する(
    tmp_path,
):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))

    assert partial_store.features == []
    assert partial_store.skipped_counts == {}
    assert partial_store.geocoded_counts == {}


def test_featuresプロパティの検証_返された一覧を変更した場合_内部状態は影響を受けない(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))
    partial_store.add_feature(_feature("https://example.com/a"))

    returned = partial_store.features
    returned.append(_feature("https://example.com/b"))
    returned.clear()

    assert len(partial_store.features) == 1
    assert partial_store.features[0].properties.source_url == "https://example.com/a"


def test_skipped_countsプロパティの検証_返された辞書を変更した場合_内部状態は影響を受けない(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))
    partial_store.add_skip("13")

    returned = partial_store.skipped_counts
    returned["13"] = 999
    returned["27"] = 1

    assert partial_store.skipped_counts == {"13": 1}


def test_geocoded_countsプロパティの検証_返された辞書を変更した場合_内部状態は影響を受けない(tmp_path):
    partial_store = SapaPartialStore(store=_make_store(tmp_path))
    partial_store.add_geocoded("13")

    returned = partial_store.geocoded_counts
    returned["13"] = 999
    returned["27"] = 1

    assert partial_store.geocoded_counts == {"13": 1}
