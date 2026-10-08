# /// script
# requires-python = ">=3.12"
# dependencies = ["fastapi>=0.115", "uvicorn>=0.30"]
# ///
"""ccorch manager: local web UI to configure ccorch per repository and install it into repos.

Run via `ccorch manage` (or `uv run --script server.py`). Binds to 127.0.0.1 only. Mutating
requests must carry the `X-CCorch` header (blocks cross-site form posts) and the Host header must
be local (blocks DNS rebinding).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.request
import webbrowser
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from ccorch_lib import branch, claude, config, gate, install, intake, terminal  # noqa: E402
from ccorch_lib.git import Git, GitError, find_root  # noqa: E402
from ccorch_lib.inbox import Inbox, InboxError  # noqa: E402
from ccorch_lib.state import StateStore  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_MARKET = {"name": "ccorch-tools", "url": "", "ref": "main"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def registry_path() -> Path:
    override = os.environ.get("CCORCH_MANAGER_HOME")
    base = Path(override) if override else Path.home() / ".ccorch"
    return base / "manager.json"


class Registry:
    """Known repos + marketplace settings, stored in ~/.ccorch/manager.json."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"repos": [], "marketplace": dict(DEFAULT_MARKET)}
        data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        data.setdefault("repos", [])
        data["marketplace"] = {**DEFAULT_MARKET, **data.get("marketplace", {})}
        return data

    def write(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --- request bodies ------------------------------------------------------------------------


class AddRepo(BaseModel):
    path: str


class MarketBody(BaseModel):
    name: str
    url: str
    ref: str = "main"


class ConfigBody(BaseModel):
    config: dict[str, Any]


class IntakeBody(BaseModel):
    text: str


class InboxBody(BaseModel):
    tickets: list[dict[str, Any]]


class ApplyBody(BaseModel):
    config: dict[str, Any]
    commit: bool = False


class BranchPreview(BaseModel):
    branch: dict[str, Any]
    type: str
    ticket_id: str
    title: str


# --- helpers -------------------------------------------------------------------------------


def _repo_by_id(reg: Registry, repo_id: int) -> Path:
    repos = reg.read()["repos"]
    if not 0 <= repo_id < len(repos):
        raise HTTPException(404, "unknown repo")
    return Path(repos[repo_id])


def _market(reg: Registry) -> install.Marketplace | None:
    m = reg.read()["marketplace"]
    return install.Marketplace(m["name"], m["url"], m["ref"]) if m["url"].strip() else None


def _summary(repo_id: int, path: Path, market_name: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "id": repo_id,
        "path": str(path),
        "name": path.name,
        "exists": path.is_dir(),
        "is_git": False,
    }
    if not path.is_dir() or find_root(path) is None:
        return info
    g = Git(path)
    info.update(
        is_git=True,
        branch=g.current_branch(),
        remote_url=g.remote_url(),
        **install.install_status(path, market_name),
    )
    try:
        state = StateStore(g.git_dir()).active()
    except GitError:
        state = None
    info["active_ticket"] = (
        {"ticket_id": state.ticket_id, "title": state.title, "branch": state.branch}
        if state
        else None
    )
    return info


def _full_config(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = config.deep_merge(config.DEFAULTS, raw)
    config.validate(cfg)
    return cfg


def _errors(raw: dict[str, Any]) -> list[str]:
    try:
        _full_config(raw)
    except config.ConfigError as exc:
        return str(exc).split("; ")
    return []


# --- app -----------------------------------------------------------------------------------


def create_app(reg: Registry) -> FastAPI:
    app = FastAPI(title="ccorch manager", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Response:
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS and host != "testserver":
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("x-ccorch") != "1"
        ):
            return JSONResponse({"detail": "missing X-CCorch header"}, status_code=403)
        response: Response = await call_next(request)
        return response

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "app": "ccorch-manager",
            "defaults": config.DEFAULTS,
            "ticket_types": list(config.TICKET_TYPES),
            "model_choices": list(config.MODEL_CHOICES),
            "marketplace": reg.read()["marketplace"],
        }

    @app.put("/api/marketplace")
    def set_market(body: MarketBody) -> dict[str, Any]:
        data = reg.read()
        data["marketplace"] = body.model_dump()
        reg.write(data)
        market: dict[str, Any] = data["marketplace"]
        return market

    @app.get("/api/repos")
    def list_repos() -> list[dict[str, Any]]:
        data = reg.read()
        name = data["marketplace"]["name"]
        return [_summary(i, Path(p), name) for i, p in enumerate(data["repos"])]

    @app.post("/api/repos")
    def add_repo(body: AddRepo) -> dict[str, Any]:
        path = Path(body.path).expanduser()
        root = find_root(path) if path.is_dir() else None
        if root is None:
            raise HTTPException(400, f"not a git repository: {path}")
        data = reg.read()
        resolved = str(root.resolve())
        if resolved not in data["repos"]:
            data["repos"].append(resolved)
            reg.write(data)
        idx = data["repos"].index(resolved)
        return _summary(idx, Path(resolved), data["marketplace"]["name"])

    @app.delete("/api/repos/{repo_id}")
    def remove_repo(repo_id: int) -> dict[str, bool]:
        data = reg.read()
        _repo_by_id(reg, repo_id)
        data["repos"].pop(repo_id)
        reg.write(data)
        return {"ok": True}

    @app.get("/api/repos/{repo_id}/config")
    def get_config(repo_id: int) -> dict[str, Any]:
        path = _repo_by_id(reg, repo_id)
        detected = install.detect_defaults(path)
        has_file = config.has_config(path)
        shared: dict[str, Any] = config.read_toml(path / config.CONFIG_REL) if has_file else {}
        try:
            cfg = config.deep_merge(detected if not has_file else config.DEFAULTS, shared)
            load_error = None
        except config.ConfigError as exc:
            cfg, load_error = detected, str(exc)
        return {
            "config": cfg,
            "has_file": has_file,
            "detected": detected,
            "local_overrides": config.read_toml(path / config.LOCAL_CONFIG_REL),
            "errors": _errors(cfg) if load_error is None else [load_error],
        }

    @app.post("/api/repos/{repo_id}/validate")
    def validate(repo_id: int, body: ConfigBody) -> dict[str, Any]:
        _repo_by_id(reg, repo_id)
        return {"errors": _errors(body.config)}

    @app.post("/api/preview/branch")
    def preview_branch(body: BranchPreview) -> dict[str, Any]:
        b = config.deep_merge(config.DEFAULTS["branch"], body.branch)
        try:
            name = branch.render(
                b["template"],
                body.type,
                body.ticket_id,
                body.title,
                b["type_prefix"],
                int(b["slug_max_len"]),
            )
        except (branch.BranchNameError, ValueError, TypeError) as exc:
            return {"name": "", "error": str(exc)}
        return {"name": name, "error": None}

    @app.post("/api/repos/{repo_id}/plan")
    def plan(repo_id: int, body: ConfigBody) -> dict[str, Any]:
        path = _repo_by_id(reg, repo_id)
        errors = _errors(body.config)
        if errors:
            return {"errors": errors, "changes": [], "marketplace_missing": False}
        changes = install.plan(path, _full_config(body.config), _market(reg))
        return {
            "errors": [],
            "changes": [{"path": c.path, "old": c.old, "new": c.new} for c in changes],
            "marketplace_missing": _market(reg) is None,
        }

    @app.post("/api/repos/{repo_id}/apply")
    def apply(repo_id: int, body: ApplyBody) -> dict[str, Any]:
        path = _repo_by_id(reg, repo_id)
        errors = _errors(body.config)
        if errors:
            raise HTTPException(400, "; ".join(errors))
        changes = install.plan(path, _full_config(body.config), _market(reg))
        written = install.apply(path, changes)
        sha = None
        if body.commit and written:
            g = Git(path)
            g.run("add", "--", *written)
            g.run("commit", "-m", "chore: configure ccorch", "--", *written)
            sha = g.head()
        return {"written": written, "commit": sha}

    @app.post("/api/repos/{repo_id}/test-gate")
    def test_gate(repo_id: int, body: ConfigBody) -> dict[str, Any]:
        path = _repo_by_id(reg, repo_id)
        g = config.deep_merge(config.DEFAULTS["gate"], body.config.get("gate", {}))
        result = gate.run(list(g["build"]), list(g["test"]), path, float(g["timeout_s"]))
        return {
            "passed": result.passed,
            "exit_code": result.exit_code,
            "command": result.command,
            "skipped": result.skipped,
            "output": gate.tail(result.output_tail, 120),
        }

    @app.get("/api/repos/{repo_id}/activity")
    def activity(repo_id: int) -> dict[str, Any]:
        path = _repo_by_id(reg, repo_id)
        store = StateStore(Git(path).git_dir())
        state = store.active()
        return {"active": state.__dict__ if state else None, "history": store.read_history(30)}

    # --- transcript -> tickets (headless claude, subscription) and the inbox ---------------

    def _inbox(repo_id: int) -> tuple[Path, Inbox]:
        path = _repo_by_id(reg, repo_id)
        return path, Inbox(StateStore(Git(path).git_dir()))

    @app.get("/api/claude")
    def claude_info() -> dict[str, Any]:
        exe = claude.resolve()
        _, removed = claude.child_env()
        return {
            "path": exe,
            "version": claude.version(exe) if exe else None,
            "api_key_env": bool(removed),
        }

    @app.post("/api/claude/update")
    def claude_update() -> dict[str, Any]:
        exe = claude.resolve()
        if exe is None:
            raise HTTPException(400, "claude not found")
        return {"output": claude.update(exe), "version": claude.version(exe)}

    @app.post("/api/repos/{repo_id}/intake")
    def run_intake(repo_id: int, body: IntakeBody) -> dict[str, Any]:
        path, inbox = _inbox(repo_id)
        try:
            cfg = config.load(path)
        except config.ConfigError as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            drafts, notes, answer = intake.extract(body.text, cfg["models"]["intake"], path)
        except claude.ClaudeError as exc:
            raise HTTPException(502, str(exc)) from exc
        fresh: Iterator[str] = iter(inbox.next_ids(cfg["intake"]["id_prefix"], len(drafts)))
        tickets = []
        for d in drafts:
            ext = str(d.get("external_id", "")).strip()
            tickets.append({**d, "id": ext or next(fresh)})
        return {
            "tickets": tickets,
            "notes": notes,
            "cost_usd": answer.cost_usd,
            "duration_ms": answer.duration_ms,
            "model": answer.model,
        }

    @app.get("/api/repos/{repo_id}/inbox")
    def list_inbox(repo_id: int) -> list[dict[str, Any]]:
        _, inbox = _inbox(repo_id)
        return inbox.items()

    @app.post("/api/repos/{repo_id}/inbox")
    def add_inbox(repo_id: int, body: InboxBody) -> dict[str, Any]:
        _, inbox = _inbox(repo_id)
        try:
            return {"saved": inbox.add(body.tickets)}
        except InboxError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/repos/{repo_id}/inbox/{ticket_id}")
    def delete_inbox(repo_id: int, ticket_id: str) -> dict[str, bool]:
        _, inbox = _inbox(repo_id)
        return {"deleted": inbox.delete(ticket_id)}

    @app.get("/api/repos/{repo_id}/inbox/{ticket_id}/command")
    def inbox_command(repo_id: int, ticket_id: str) -> dict[str, str]:
        path = _repo_by_id(reg, repo_id)
        prompt = f"/ccorch:ticket {ticket_id}"
        return {"slash": prompt, "shell": f"cd {path} && {terminal.display_command(prompt)}"}

    @app.post("/api/repos/{repo_id}/inbox/{ticket_id}/launch")
    def inbox_launch(repo_id: int, ticket_id: str) -> dict[str, Any]:
        path, inbox = _inbox(repo_id)
        if inbox.get(ticket_id) is None:
            raise HTTPException(404, "ticket not in inbox")
        exe = claude.resolve()
        if exe is None:
            raise HTTPException(400, "claude not found")
        try:
            terminal.open_terminal(path, terminal.claude_argv(exe, f"/ccorch:ticket {ticket_id}"))
        except (terminal.TerminalError, OSError) as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"launched": True}

    @app.get("/api/fs")
    def browse(path: str = "") -> dict[str, Any]:
        base = Path(path).expanduser() if path else Path.home()
        if not base.is_dir():
            raise HTTPException(400, f"not a directory: {base}")
        entries = []
        try:
            children = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except PermissionError:
            children = []
        for child in children:
            if child.name.startswith(".") or not child.is_dir():
                continue
            entries.append(
                {"name": child.name, "path": str(child), "is_git": (child / ".git").exists()}
            )
        parent = str(base.parent) if base.parent != base else None
        return {
            "path": str(base),
            "parent": parent,
            "is_git": (base / ".git").exists(),
            "entries": entries,
        }

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        target = (STATIC / full_path).resolve()
        if full_path and target.is_file() and STATIC.resolve() in target.parents:
            return FileResponse(target)
        index = STATIC / "index.html"
        if index.is_file():
            return FileResponse(index)
        return Response(
            "UI not built: run `npm run build` in manager-web/", media_type="text/plain"
        )

    return app


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=1) as resp:
            return bool(json.loads(resp.read()).get("app") == "ccorch-manager")
    except (OSError, ValueError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="ccorch manager UI")
    parser.add_argument("--port", type=int, default=7420)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    if _already_running(args.port):
        print(f"ccorch manager already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    import uvicorn

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"ccorch manager at {url}  (Ctrl+C to stop)")
    uvicorn.run(
        create_app(Registry(registry_path())), host="127.0.0.1", port=args.port, log_level="warning"
    )


if __name__ == "__main__":
    main()
