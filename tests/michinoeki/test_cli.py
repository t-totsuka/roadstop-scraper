"""実行エントリポイント(cli.main)の検証。

タスク6の観測可能な完了条件を検証する: 範囲指定なし・地方区分指定・都道府県指定の
各ケースで正常に起動でき(``runner.run_scope``が対応する``ScopeSpec``で呼び出される
こと)、不正な範囲指定(存在しない地方区分・存在しない都道府県コード・地方区分と
都道府県コードの同時指定)の場合は標準エラー出力へメッセージが表示され非ゼロの
終了コードが返り、``run_scope``が一切呼び出されない(=通信が一切発生しない)ことを
検証する。design.mdの方針(cli component Responsibilities & Constraints)に従い、
範囲の妥当性検証は``argparse``自体の検証機能(``choices=``等)には委ねず、
``scope.resolve_scope``に一本化されていることを確認するため、``run_scope``のみを
モンキーパッチしてHTTP通信そのものが発生しないことを担保する
(``resolve_scope``はテスト対象外・本物のまま通す)。
"""

from __future__ import annotations

import pytest

from roadstop_scraper.michinoeki import cli
from roadstop_scraper.michinoeki.scope import ScopeSpec


@pytest.fixture
def _capture_run_scope(monkeypatch: pytest.MonkeyPatch) -> list[ScopeSpec]:
    """``cli.run_scope``をモンキーパッチし、呼び出された``ScopeSpec``を記録する。

    戻り値のリストへ呼び出しごとの``ScopeSpec``を追記する。呼び出しがなければ
    空リストのままであり、これによって「run_scopeが一切呼び出されない」ことを
    検証できる。
    """
    calls: list[ScopeSpec] = []

    def _fake_run_scope(spec: ScopeSpec, **_kwargs: object) -> list[None]:
        calls.append(spec)
        return []

    monkeypatch.setattr(cli, "run_scope", _fake_run_scope)
    return calls


def test_範囲指定なしの検証_引数を渡さない場合_全国のScopeSpecでrun_scopeが呼ばれ0を返す(
    _capture_run_scope: list[ScopeSpec],
) -> None:
    exit_code = cli.main([])

    assert exit_code == 0
    assert _capture_run_scope == [ScopeSpec(region=None, prefecture_code=None)]


def test_地方区分指定の検証_regionにkantoを指定した場合_対応するScopeSpecでrun_scopeが呼ばれ0を返す(
    _capture_run_scope: list[ScopeSpec],
) -> None:
    exit_code = cli.main(["--region", "kanto"])

    assert exit_code == 0
    assert _capture_run_scope == [ScopeSpec(region="kanto", prefecture_code=None)]


def test_都道府県指定の検証_prefecture_codeに01を指定した場合_対応するScopeSpecでrun_scopeが呼ばれ0を返す(
    _capture_run_scope: list[ScopeSpec],
) -> None:
    exit_code = cli.main(["--prefecture-code", "01"])

    assert exit_code == 0
    assert _capture_run_scope == [ScopeSpec(region=None, prefecture_code="01")]


def test_不正な地方区分の検証_存在しないregionを指定した場合_非ゼロを返しrun_scopeを呼び出さない(
    _capture_run_scope: list[ScopeSpec],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["--region", "no-such-region"])

    assert exit_code != 0
    assert _capture_run_scope == []
    assert capsys.readouterr().err != ""


def test_不正な都道府県コードの検証_存在しないprefecture_codeを指定した場合_非ゼロを返しrun_scopeを呼び出さない(
    _capture_run_scope: list[ScopeSpec],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["--prefecture-code", "99"])

    assert exit_code != 0
    assert _capture_run_scope == []
    assert capsys.readouterr().err != ""


def test_同時指定の検証_regionとprefecture_codeを両方指定した場合_非ゼロを返しrun_scopeを呼び出さない(
    _capture_run_scope: list[ScopeSpec],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["--region", "kanto", "--prefecture-code", "01"])

    assert exit_code != 0
    assert _capture_run_scope == []
    assert capsys.readouterr().err != ""


def test_プロジェクトスクリプト登録の検証_pyproject_tomlを確認した場合_michinoeki_scrapeエントリが存在する() -> None:
    import pathlib
    import tomllib

    pyproject_path = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert data["project"]["scripts"]["michinoeki-scrape"] == "roadstop_scraper.michinoeki.cli:main"
