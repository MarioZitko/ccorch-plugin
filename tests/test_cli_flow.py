"""End-to-end CLI flow against a real git repo with a bare origin."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ccorch_lib import cli, config
from ccorch_lib.git import Git
from ccorch_lib.state import StateStore
from tests.conftest import git

CHECK = (
    f'"{sys.executable}" -c "import sys; '
    "sys.exit(0 if open('app.txt').read().startswith('ok') else 1)\""
)


@pytest.fixture
def configured(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = config.deep_merge(config.DEFAULTS, {"gate": {"test": [CHECK], "max_attempts": 2}})
    config.write(repo, cfg)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "ccorch config")
    git(repo, "push")
    monkeypatch.chdir(repo)
    return repo


def store(repo: Path) -> StateStore:
    return StateStore(Git(repo).git_dir())


def test_full_ticket_flow(configured: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = configured
    assert cli.main(["start", "--id", "ABC-7", "--type", "feature", "--title", "Šifra kupca"]) == 0
    assert git(repo, "branch", "--show-current").strip() == "feature/ABC-7-sifra-kupca"

    # Dirty tree + failing gate -> the Stop hook blocks with the failure.
    (repo / "app.txt").write_text("broken\n")
    out = cli.hook_stop({"cwd": str(repo)})
    assert out is not None and out["decision"] == "block"
    assert "attempt 1/2" in out["reason"]

    # Commit refuses while the gate fails.
    assert cli.main(["commit", "--phase", "1", "--title", "Add field"]) == 1

    # Fixed tree -> hook allows the stop, commit uses the cached gate result.
    (repo / "app.txt").write_text("ok\n")
    assert cli.hook_stop({"cwd": str(repo)}) is None
    assert cli.main(["commit", "--phase", "1", "--title", "Add field", "--note", "uses X"]) == 0
    assert git(repo, "log", "-1", "--format=%s").strip() == "[ABC-7] phase 1: Add field"
    state = store(repo).active()
    assert state is not None and state.phases_done == 1 and state.notes == ["uses X"]

    # Clean tree -> hook does nothing.
    assert cli.hook_stop({"cwd": str(repo)}) is None

    capsys.readouterr()
    assert cli.main(["mr", "--description", "Adds the field.\nTested."]) == 0
    assert "no MR link" in capsys.readouterr().out  # bare origin is not GitLab
    assert "feature/ABC-7-sifra-kupca" in git(repo, "ls-remote", "--heads", "origin")
    assert store(repo).active() is None
    assert store(repo).read_history()[0]["outcome"] == "mr_opened"


def test_hook_gives_up_after_max_attempts(configured: Path) -> None:
    repo = configured
    cli.main(["start", "--id", "B-1", "--type", "bug", "--title", "x"])
    (repo / "app.txt").write_text("broken\n")
    assert cli.hook_stop({"cwd": str(repo)})["decision"] == "block"  # type: ignore[index]
    assert cli.hook_stop({"cwd": str(repo)})["decision"] == "block"  # type: ignore[index]
    give_up = cli.hook_stop({"cwd": str(repo)})
    assert give_up is not None and "systemMessage" in give_up
    # Hold disables the hook entirely.
    cli.main(["hold"])
    assert cli.hook_stop({"cwd": str(repo)}) is None


def test_start_refuses_dirty_tree_and_existing_ticket(configured: Path) -> None:
    repo = configured
    (repo / "app.txt").write_text("wip\n")
    assert cli.main(["start", "--id", "C-1", "--type", "task", "--title", "t"]) == 2
    git(repo, "checkout", "--", "app.txt")
    assert cli.main(["start", "--id", "C-1", "--type", "task", "--title", "t"]) == 0
    assert cli.main(["start", "--id", "C-2", "--type", "task", "--title", "t"]) == 2


def test_hook_warns_when_config_breaks_during_active_ticket(
    configured: Path,
) -> None:
    repo = configured
    cli.main(["start", "--id", "D-1", "--type", "bug", "--title", "x"])
    (repo / ".claude" / "ccorch.toml").write_text("[gate\nbroken", encoding="utf-8")
    out = cli.hook_stop({"cwd": str(repo)})
    assert out is not None and "decision" not in out
    assert "gate not run" in out["systemMessage"] and "ccorch.toml" in out["systemMessage"]
    # No active ticket -> silent.
    active = store(repo).active()
    assert active is not None
    store(repo).finish(active, "abandoned")
    assert cli.hook_stop({"cwd": str(repo)}) is None


def test_context_marks_inherit_models(configured: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = config.load(configured)
    cfg["models"]["planner"] = "inherit"
    config.write(configured, cfg)
    assert cli.main(["context"]) == 0
    assert "planner=inherit (omit the model parameter)" in capsys.readouterr().out


def test_hook_ignores_repos_without_active_ticket(repo: Path) -> None:
    (repo / "app.txt").write_text("dirty\n")
    assert cli.hook_stop({"cwd": str(repo)}) is None


def test_context_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["context"]) == 0
    assert "unavailable" in capsys.readouterr().out


def test_cmd_hook_reads_stdin(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(configured)})))
    assert cli.main(["hook", "stop"]) == 0
    assert capsys.readouterr().out == ""


def _review_model(capsys: pytest.CaptureFixture[str], *flags: str) -> tuple[str, str]:
    capsys.readouterr()
    assert cli.main(["review-model", *flags]) == 0
    out = capsys.readouterr().out.splitlines()
    return out[0], out[1]


def _commit_lines(repo: Path, count: int, name: str = "big.txt") -> None:
    (repo / name).write_text("ok\n" * count)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", f"add {count} lines")
    git(repo, "push", "-u", "origin", "HEAD")


def test_review_model_by_size_and_quick(
    configured: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = configured
    cli.main(["start", "--id", "R-1", "--type", "task", "--title", "small"])
    _commit_lines(repo, 42)
    assert _review_model(capsys) == ("MODEL: sonnet", "REASON: 42 changed lines (<= 150)")
    # Stored: stays the same after the diff grows past the limit.
    _commit_lines(repo, 900, "more.txt")
    assert _review_model(capsys) == ("MODEL: sonnet", "REASON: same as earlier review rounds")

    cli.main(["finish"])
    cli.main(["start", "--id", "R-2", "--type", "task", "--title", "big"])
    _commit_lines(repo, 900, "huge.txt")
    assert _review_model(capsys) == ("MODEL: opus", "REASON: 900 changed lines")

    cli.main(["finish"])
    cli.main(["start", "--id", "R-3", "--type", "task", "--title", "quick"])
    _commit_lines(repo, 900, "q.txt")
    assert _review_model(capsys, "--quick") == ("MODEL: sonnet", "REASON: quick path")


def test_review_model_limit_zero_and_inherit(
    configured: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = configured
    cfg = config.load(repo)
    cfg["workflow"]["small_review_max_lines"] = 0
    cfg["models"]["reviewer"] = "inherit"
    config.write(repo, cfg)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "cfg")
    git(repo, "push")
    cli.main(["start", "--id", "R-4", "--type", "task", "--title", "t"])
    _commit_lines(repo, 3)
    assert _review_model(capsys) == (
        "MODEL: inherit (omit the model parameter)",
        "REASON: 3 changed lines",
    )
