from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with one commit on `main` and a bare `origin` that accepts push options."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(origin, "config", "receive.advertisePushOptions", "true")
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-b", "main")
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "Test")
    git(work, "config", "commit.gpgsign", "false")
    (work / "app.txt").write_text("hello\n")
    git(work, "add", "-A")
    git(work, "commit", "-m", "init")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-u", "origin", "main")
    git(work, "remote", "set-head", "origin", "main")
    return work
