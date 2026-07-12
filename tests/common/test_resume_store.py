from pathlib import Path

import pytest

from roadstop_scraper.common import resume_store
from roadstop_scraper.common.resume_store import ResumeStore


def test_既定値の検証_DEFAULT_STATE_DIRは_resumeを指す():
    assert resume_store.DEFAULT_STATE_DIR == Path(".resume")


def test_往復の検証_saveした状態をloadすると内容が一致する(tmp_path: Path):
    store = ResumeStore(state_dir=tmp_path)
    state = {"processed_pages": [1, 2, 3], "next": "page4"}

    store.save("01_hokkaido_michinoeki", state)

    assert store.load("01_hokkaido_michinoeki") == state


def test_保存の検証_saveはstate_dirを作成しキーごとのJSONファイルを書き出す(tmp_path: Path):
    state_dir = tmp_path / "nested" / ".resume"
    store = ResumeStore(state_dir=state_dir)

    store.save("key1", {"a": 1})

    assert (state_dir / "key1.json").exists()


def test_読み込みの検証_未保存キーのloadはNoneを返す(tmp_path: Path):
    store = ResumeStore(state_dir=tmp_path)

    assert store.load("unknown_key") is None


def test_クリアの検証_clear後にloadするとNoneを返す(tmp_path: Path):
    store = ResumeStore(state_dir=tmp_path)
    store.save("key1", {"a": 1})

    store.clear("key1")

    assert store.load("key1") is None


def test_クリアの検証_未保存キーのclearはエラーにならない(tmp_path: Path):
    store = ResumeStore(state_dir=tmp_path)

    store.clear("unknown_key")


def test_独立性の検証_あるキーへの操作は他のキーに影響しない(tmp_path: Path):
    store = ResumeStore(state_dir=tmp_path)
    store.save("key1", {"a": 1})
    store.save("key2", {"b": 2})

    store.clear("key1")

    assert store.load("key1") is None
    assert store.load("key2") == {"b": 2}


def test_読み込みの検証_JSON構文が不正な状態ファイルの場合_Noneを返す(tmp_path: Path):
    store = ResumeStore(state_dir=tmp_path)
    (tmp_path / "key1.json").write_text("{broken json", encoding="utf-8")

    assert store.load("key1") is None


def test_読み込みの検証_内容が辞書でない状態ファイルの場合_Noneを返す(tmp_path: Path):
    store = ResumeStore(state_dir=tmp_path)
    (tmp_path / "key1.json").write_text("[1, 2, 3]", encoding="utf-8")

    assert store.load("key1") is None


def test_保存の検証_saveに成功した場合_一時ファイルが残らない(tmp_path: Path):
    store = ResumeStore(state_dir=tmp_path)

    store.save("key1", {"a": 1})

    assert list(tmp_path.glob("*.tmp")) == []


def test_保存の検証_置き換えが失敗した場合_既存状態が保たれ一時ファイルも残らない(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = ResumeStore(state_dir=tmp_path)
    store.save("key1", {"a": 1})

    def _fail_replace(src: str, dst: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(
        "roadstop_scraper.common._atomic_io.os.replace", _fail_replace
    )

    with pytest.raises(OSError):
        store.save("key1", {"a": 2})

    assert store.load("key1") == {"a": 1}
    assert list(tmp_path.glob("*.tmp")) == []
