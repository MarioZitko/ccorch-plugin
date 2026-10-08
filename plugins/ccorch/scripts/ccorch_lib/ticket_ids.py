"""Next ticket number: continue after the highest one the team already used (stdlib only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ccorch_lib import jira
from ccorch_lib.git import Git
from ccorch_lib.state import StateStore

DEFAULT_WIDTH = 3
LOG_LIMIT = 2000


@dataclass
class NextIds:
    ids: list[str]
    source: str
    last: str | None
    warning: str | None


@dataclass
class _Top:
    number: int
    width: int
    where: str


def _pattern(prefix: str) -> re.Pattern[str]:
    # Not inside a longer word (XPROJ-9) and not followed by a letter/digit (PROJ-12a).
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(prefix)}-(\d+)(?![A-Za-z0-9])")


def _highest(texts: list[str], prefix: str, where: str) -> _Top | None:
    best: _Top | None = None
    for m in _pattern(prefix).finditer("\n".join(texts)):
        n = int(m.group(1))
        if best is None or n > best.number:
            best = _Top(n, len(m.group(1)), where)
    return best


def numbers_local(store: StateStore, prefix: str) -> _Top | None:
    """Highest number in this clone's inbox, past tickets and the active ticket."""
    inbox_dir = store.dir / "inbox"
    used = [p.stem for p in inbox_dir.glob("*.json")] if inbox_dir.is_dir() else []
    used += [str(h.get("ticket_id", "")) for h in store.read_history(10_000)]
    state = store.load()
    if state:
        used.append(state.ticket_id)
    exact = re.compile(rf"^{re.escape(prefix)}-\d+$")
    return _highest([u for u in used if exact.match(u)], prefix, "this clone")


def numbers_git(git: Git, base: str, prefix: str) -> _Top | None:
    """Highest number in remote branch names and the base branch's commit messages."""
    if not git.has_remote():
        raise RuntimeError(f"no remote named {git.remote!r}")
    remote = git.remote
    heads = git.ls_remote_heads()
    git.run("fetch", "--quiet", remote, base)
    log = git.run("log", "-n", str(LOG_LIMIT), "--format=%s%n%b", f"{remote}/{base}").stdout
    found = [t for t in (_highest(heads, prefix, remote), _highest([log], prefix, remote)) if t]
    return max(found, key=lambda t: t.number, default=None)


def numbers_jira(cfg: dict[str, Any], prefix: str) -> _Top | None:
    client = jira.client_for(cfg)
    if client is None:
        raise RuntimeError("Jira is off or no login is saved")
    key = client.search_last_key(cfg["jira"]["project_key"])
    return _highest([key], prefix, "Jira") if key else None


def next_ids(cfg: dict[str, Any], root: Path, store: StateStore, count: int) -> NextIds:
    """`count` fresh ids. Falls back to this clone's numbers (with a warning), never raises."""
    prefix: str = cfg["intake"]["id_prefix"]
    source: str = cfg["intake"]["id_source"]
    local = numbers_local(store, prefix)
    remote: _Top | None = None
    warning: str | None = None
    if source != "local":
        try:
            if source == "git":
                git = Git(root, cfg["repo"]["remote"])
                remote = numbers_git(git, cfg["repo"]["base_branch"], prefix)
            else:
                remote = numbers_jira(cfg, prefix)
        except Exception as exc:
            where = cfg["repo"]["remote"] if source == "git" else "Jira"
            warning = f"Couldn't read {where}: {exc} - numbered from this clone only"
            source = "local"
    tops = [t for t in (local, remote) if t is not None]
    top = max(tops, key=lambda t: t.number, default=None)
    # Local numbering is padded (T-001); remote numbering copies the width the team already uses.
    width = top.width if top is not None and top is remote else DEFAULT_WIDTH
    start = top.number if top else 0
    ids = [f"{prefix}-{start + i:0{width}d}" for i in range(1, count + 1)]
    last = f"{prefix}-{top.number:0{top.width}d} ({top.where})" if top else None
    return NextIds(ids=ids, source=source, last=last, warning=warning)
