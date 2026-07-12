import importlib
import subprocess
from pathlib import Path


def test_commonパッケージの検証_importが要求された場合_成功する():
    module = importlib.import_module("roadstop_scraper.common")

    assert module is not None


def test_resumeディレクトリの検証_gitignore設定を確認した場合_未追跡一覧に現れない():
    repo_root = Path(__file__).resolve().parents[2]
    resume_marker = repo_root / ".resume" / "dummy.json"
    resume_marker.parent.mkdir(exist_ok=True)
    resume_marker.write_text("{}", encoding="utf-8")

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        resume_marker.unlink()

    untracked = [line for line in result.stdout.splitlines() if ".resume/" in line]
    assert untracked == []
