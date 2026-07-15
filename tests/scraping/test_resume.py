"""UrlResumeTrackerのユニットテスト。

実体の``ResumeStore``を``tmp_path``に向けて使い、実際の永続化往復を
検証する(design.mdのテスト方針: 不要なモックを導入しない)。
"""

from __future__ import annotations

from pathlib import Path

from roadstop_scraper.common.resume_store import ResumeStore
from roadstop_scraper.scraping.resume import UrlResumeTracker


def test_未処理判定_未記録のURLはis_processedがFalseを返す(tmp_path: Path) -> None:
    store = ResumeStore(state_dir=tmp_path)
    tracker = UrlResumeTracker("michinoeki", store=store)

    assert tracker.is_processed("https://example.com/a") is False


def test_記録の検証_mark_processed後は同一インスタンスでis_processedがTrueを返す(
    tmp_path: Path,
) -> None:
    store = ResumeStore(state_dir=tmp_path)
    tracker = UrlResumeTracker("michinoeki", store=store)

    tracker.mark_processed("https://example.com/a")

    assert tracker.is_processed("https://example.com/a") is True


def test_永続化の検証_mark_processed後に新規インスタンスを再構築してもis_processedがTrueを返す(
    tmp_path: Path,
) -> None:
    store = ResumeStore(state_dir=tmp_path)
    tracker = UrlResumeTracker("michinoeki", store=store)
    tracker.mark_processed("https://example.com/a")

    rebuilt = UrlResumeTracker("michinoeki", store=store)

    assert rebuilt.is_processed("https://example.com/a") is True


def test_永続化の検証_複数回のmark_processedで全URLの集合が保存される(
    tmp_path: Path,
) -> None:
    store = ResumeStore(state_dir=tmp_path)
    tracker = UrlResumeTracker("michinoeki", store=store)

    tracker.mark_processed("https://example.com/a")
    tracker.mark_processed("https://example.com/b")
    tracker.mark_processed("https://example.com/c")

    rebuilt = UrlResumeTracker("michinoeki", store=store)
    assert rebuilt.is_processed("https://example.com/a") is True
    assert rebuilt.is_processed("https://example.com/b") is True
    assert rebuilt.is_processed("https://example.com/c") is True


def test_保存形状の検証_ResumeStoreにはprocessed_urlsキーのリストとして保存される(
    tmp_path: Path,
) -> None:
    store = ResumeStore(state_dir=tmp_path)
    tracker = UrlResumeTracker("michinoeki", store=store)

    tracker.mark_processed("https://example.com/a")

    saved = store.load("michinoeki")
    assert saved is not None
    assert set(saved["processed_urls"]) == {"https://example.com/a"}


def test_クリアの検証_clear後は同一インスタンスでis_processedがFalseに戻る(
    tmp_path: Path,
) -> None:
    store = ResumeStore(state_dir=tmp_path)
    tracker = UrlResumeTracker("michinoeki", store=store)
    tracker.mark_processed("https://example.com/a")

    tracker.clear()

    assert tracker.is_processed("https://example.com/a") is False


def test_クリアの検証_clear後に新規インスタンスを再構築してもis_processedがFalseを返す(
    tmp_path: Path,
) -> None:
    store = ResumeStore(state_dir=tmp_path)
    tracker = UrlResumeTracker("michinoeki", store=store)
    tracker.mark_processed("https://example.com/a")
    tracker.clear()

    rebuilt = UrlResumeTracker("michinoeki", store=store)

    assert rebuilt.is_processed("https://example.com/a") is False


def test_初期化の検証_未保存キーの場合は例外を送出せず空集合から開始する(
    tmp_path: Path,
) -> None:
    store = ResumeStore(state_dir=tmp_path)

    tracker = UrlResumeTracker("unknown_key", store=store)

    assert tracker.is_processed("https://example.com/a") is False


def test_初期化の検証_破損した状態ファイルの場合は例外を送出せず空集合から開始する(
    tmp_path: Path,
) -> None:
    store = ResumeStore(state_dir=tmp_path)
    (tmp_path / "michinoeki.json").write_text("{broken json", encoding="utf-8")

    tracker = UrlResumeTracker("michinoeki", store=store)

    assert tracker.is_processed("https://example.com/a") is False


def test_初期化の検証_storeを省略した場合は既定のResumeStoreで動作する() -> None:
    tracker = UrlResumeTracker("unknown_key_for_default_store_test")

    assert tracker.is_processed("https://example.com/a") is False
