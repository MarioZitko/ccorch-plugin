"""Thin `git` wrapper: explicit argv, never a shell. Ported from ccorch `adapters/git_cli.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT_S = 300

# GitLab prints e.g. "remote:   https://gitlab.example.com/group/proj/-/merge_requests/12"
_MR_URL = re.compile(r"https?://[^\s]+/-/merge_requests/\d+")


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, output: str) -> None:
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {output.strip()}")
        self.returncode = returncode
        self.output = output


def _creationflags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def parse_mr_url(output: str) -> str | None:
    match = _MR_URL.search(output)
    return match.group(0) if match else None


def find_root(start: Path) -> Path | None:
    """Top-level directory of the git work tree containing `start`, or None."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=30,
            check=False,
            creationflags=_creationflags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip())


@dataclass
class PushResult:
    mr_url: str | None
    output: str


class Git:
    def __init__(self, repo: Path, remote: str = "origin") -> None:
        self.repo = repo
        self.remote = remote

    def run(
        self, *args: str, check: bool = True, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_S,
            check=False,
            env={**os.environ, **env} if env else None,
            creationflags=_creationflags(),
        )
        if check and proc.returncode != 0:
            raise GitError(list(args), proc.returncode, proc.stderr or proc.stdout)
        return proc

    def git_dir(self) -> Path:
        out = self.run("rev-parse", "--absolute-git-dir").stdout.strip()
        return Path(out)

    def is_valid_branch_name(self, name: str) -> bool:
        if not name or name.startswith("-"):
            return False
        return self.run("check-ref-format", "--branch", name, check=False).returncode == 0

    def status_porcelain(self) -> str:
        return self.run("status", "--porcelain").stdout

    def is_clean(self) -> bool:
        return not self.status_porcelain().strip()

    def current_branch(self) -> str:
        return self.run("branch", "--show-current").stdout.strip()

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").stdout.strip()

    def ref_exists(self, ref: str) -> bool:
        return self.run("rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0

    def has_remote(self) -> bool:
        return self.remote in self.run("remote").stdout.split()

    def remote_url(self) -> str:
        proc = self.run("remote", "get-url", self.remote, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def remote_default_branch(self) -> str | None:
        proc = self.run("symbolic-ref", "--quiet", f"refs/remotes/{self.remote}/HEAD", check=False)
        ref = proc.stdout.strip()
        prefix = f"refs/remotes/{self.remote}/"
        return ref[len(prefix) :] if proc.returncode == 0 and ref.startswith(prefix) else None

    def ls_remote_heads(self) -> list[str]:
        """Branch names on the remote (no fetch needed)."""
        out = self.run("ls-remote", "--heads", self.remote).stdout
        return [ln.partition("refs/heads/")[2] for ln in out.splitlines() if "refs/heads/" in ln]

    def fetch(self) -> None:
        self.run("fetch", self.remote, "--prune")

    def base_ref(self, base: str) -> str:
        """Prefer the remote-tracking base (freshly fetched) over a possibly stale local one."""
        if self.ref_exists(f"refs/remotes/{self.remote}/{base}"):
            return f"{self.remote}/{base}"
        return base

    def create_branch(self, base: str, name: str) -> None:
        cmd = ["switch", "-c", name]
        if not self.is_valid_branch_name(name):
            raise GitError(cmd, 1, f"invalid branch name: {name!r}")
        if self.ref_exists(f"refs/heads/{name}"):
            raise GitError(cmd, 1, f"branch already exists locally: {name}")
        if self.ref_exists(f"refs/remotes/{self.remote}/{name}"):
            raise GitError(cmd, 1, f"branch already exists on {self.remote}: {name}")
        self.run("switch", "-c", name, "--no-track", self.base_ref(base))

    def tree_fingerprint(self) -> str:
        """Hash of the full working tree incl. untracked files, without touching the real index."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            self.run("read-tree", "HEAD", env=env)
            self.run("add", "-A", env=env)
            return self.run("write-tree", env=env).stdout.strip()

    def commit_all(self, message: str) -> str | None:
        self.run("add", "-A")
        if not self.run("diff", "--cached", "--name-only").stdout.strip():
            return None
        self.run("commit", "-m", message)
        return self.head()

    def diff_stat(self, base: str) -> str:
        return self.run("diff", "--stat", f"{self.base_ref(base)}...HEAD").stdout

    def changed_lines(self, base: str) -> int:
        """Inserted + deleted lines vs the base; binary files count 0."""
        out = self.run("diff", "--numstat", f"{self.base_ref(base)}...HEAD").stdout
        total = 0
        for line in out.splitlines():
            added, _, rest = line.partition("\t")
            deleted = rest.partition("\t")[0]
            if added.isdigit() and deleted.isdigit():
                total += int(added) + int(deleted)
        return total

    def push_with_options(self, branch: str, options: list[str]) -> PushResult:
        args = ["push", "-u", self.remote, branch]
        for opt in options:
            args += ["-o", opt]
        proc = self.run(*args)
        output = (proc.stderr or "") + (proc.stdout or "")
        return PushResult(mr_url=parse_mr_url(output), output=output)
