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
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from ccorch_lib import (  # noqa: E402
    branch,
    claude,
    config,
    gate,
    install,
    intake,
    jira,
    plugin_update,
    terminal,
)
from ccorch_lib.git import Git, GitError, find_root  # noqa: E402
from ccorch_lib.home import ccorch_home  # noqa: E402
from ccorch_lib.inbox import Inbox, InboxError  # noqa: E402
from ccorch_lib.state import StateStore  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
PLUGIN_JSON = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"
VERSION = str(json.loads(PLUGIN_JSON.read_text(encoding="utf-8")).get("version", "dev"))
DEFAULT_MARKET = {"name": "ccorch-tools", "url": "", "ref": "main"}
START_MODES = ("", "quick", "plan")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def registry_path() -> Path:
    return ccorch_home() / "manager.json"


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
    create_in_jira: bool = False


class JiraCredsBody(BaseModel):
    url: str
    email: str = ""
    token: str = ""


class JiraMoveBody(BaseModel):
    status: str


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


def create_app(reg: Registry, port: int = 7420) -> FastAPI:
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

    @app.post("/api/shutdown")
    def shutdown() -> dict[str, bool]:
        # Lets a newer plugin version replace a still-running older settings page.
        threading.Timer(0.3, os._exit, (0,)).start()
        return {"ok": True}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "app": "ccorch-manager",
            "version": VERSION,
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

    def _exe() -> str:
        exe = claude.resolve()
        if exe is None:
            raise HTTPException(400, "claude not found")
        return exe

    def _plugin_status() -> dict[str, Any]:
        try:
            return plugin_update.status(_exe(), VERSION)
        except plugin_update.UpdateError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/plugin")
    def plugin_info() -> dict[str, Any]:
        return _plugin_status()

    @app.post("/api/plugin/check")
    def plugin_check() -> dict[str, Any]:
        current = _plugin_status()
        if current["marketplace"]:
            try:
                plugin_update.refresh(_exe(), current["marketplace"])
            except plugin_update.UpdateError as exc:
                raise HTTPException(502, str(exc)) from exc
        return _plugin_status()

    @app.post("/api/plugin/update")
    def plugin_do_update() -> dict[str, Any]:
        current = _plugin_status()
        if not current["plugin_id"]:
            raise HTTPException(400, "ccorch is not installed as a plugin (development checkout)")
        try:
            output = plugin_update.update(_exe(), current["plugin_id"])
        except plugin_update.UpdateError as exc:
            raise HTTPException(502, str(exc)) from exc
        after = _plugin_status()
        relaunching = False
        new_server = Path(after["install_path"] or "") / "manager" / "server.py"
        if (
            not after["dev_checkout"]
            and after["installed_version"] != VERSION
            and new_server.is_file()
        ):
            # The new version's server replaces this one (it asks us to shut down).
            _spawn_detached(
                [
                    "uv",
                    "run",
                    "--quiet",
                    "--script",
                    str(new_server),
                    "--port",
                    str(port),
                    "--no-browser",
                ]
            )
            relaunching = True
        return {**after, "output": output, "relaunching": relaunching}

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
        path, inbox = _inbox(repo_id)
        if not body.create_in_jira:
            try:
                return {"saved": inbox.add(body.tickets)}
            except InboxError as exc:
                raise HTTPException(400, str(exc)) from exc
        cfg, client = _jira_client(path)
        saved: list[str] = []
        failed: list[dict[str, Any]] = []
        for draft in body.tickets:
            try:
                ticket = inbox.normalize_ticket(draft)
                if jira.is_jira_key(cfg, ticket["id"]):
                    # Already an issue (e.g. the transcript named PROJ-9): link it, don't create.
                    key = ticket["id"]
                    ticket = {
                        **ticket,
                        "jira_key": key,
                        "jira_url": f"{client.base}/browse/{key}",
                    }
                else:
                    jc = cfg["jira"]
                    key = client.create_issue(
                        jc["project_key"],
                        jc["issue_types"][ticket["type"]],
                        ticket["title"],
                        jira.ticket_description(ticket),
                    )
                    ticket = {
                        **ticket,
                        "id": key,
                        "jira_key": key,
                        "jira_url": f"{client.base}/browse/{key}",
                        "jira_status": "",
                    }
                saved += inbox.add([ticket])
            except (jira.JiraError, InboxError) as exc:
                failed.append({"draft": draft, "error": str(exc)})
        return {"saved": saved, "failed": failed}

    # --- Jira (the login is personal: ~/.ccorch/credentials.json, never the repo) ----------

    def _jira_client(path: Path) -> tuple[dict[str, Any], jira.Jira]:
        try:
            cfg = config.load(path)
        except config.ConfigError as exc:
            raise HTTPException(400, str(exc)) from exc
        client = jira.client_for(cfg)
        if client is None:
            raise HTTPException(
                400, "Jira is off for this repo, or no login is saved (Your Jira login)"
            )
        return cfg, client

    @app.get("/api/jira/credentials")
    def jira_creds(url: str = "") -> dict[str, Any]:
        return jira.creds_status(url)

    @app.put("/api/jira/credentials")
    def jira_save_creds(body: JiraCredsBody) -> dict[str, Any]:
        try:
            jira.save_creds(body.url, body.email, body.token)
        except (jira.JiraError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return jira.creds_status(body.url)

    @app.post("/api/repos/{repo_id}/jira/test")
    def jira_test(repo_id: int, body: ConfigBody) -> dict[str, Any]:
        _repo_by_id(reg, repo_id)
        errors = _errors(body.config)
        out: dict[str, Any] = {
            "ok": False,
            "user": "",
            "project_name": "",
            "issue_types": [],
            "statuses": [],
            "problems": list(errors),
        }
        if errors:
            return out
        jc = _full_config(body.config)["jira"]
        creds = jira.load_creds(jc["url"]) if jc["url"] else None
        if not jc["enabled"] or creds is None:
            out["problems"].append("Turn Jira on and save your login first.")
            return out
        client = jira.Jira(jc["url"], jc["deployment"], creds)
        try:
            me = client.myself()
            project = client.project(jc["project_key"])
            statuses = client.statuses(jc["project_key"])
        except jira.JiraError as exc:
            out["problems"].append(str(exc))
            return out
        out.update(
            ok=True,
            user=str(me.get("displayName") or me.get("name") or ""),
            project_name=project["name"],
            issue_types=project["issue_types"],
            statuses=statuses,
        )
        known_types = {t.lower() for t in project["issue_types"]}
        known_status = {s.lower() for s in statuses}
        for ticket_type, name in jc["issue_types"].items():
            if name.lower() not in known_types:
                out["problems"].append(f"Issue type {name!r} ({ticket_type}) is not in the project")
        for event, name in jc["move_to"].items():
            if name and name.lower() not in known_status:
                out["problems"].append(f"Status {name!r} ({event}) is not in the project")
        return out

    @app.get("/api/repos/{repo_id}/jira/issue/{key}")
    def jira_issue(repo_id: int, key: str) -> dict[str, Any]:
        _, client = _jira_client(_repo_by_id(reg, repo_id))
        try:
            issue = client.get_issue(key)
            targets = sorted({t["to"] for t in client.transitions(key) if t["to"]})
        except jira.JiraError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"key": key, "status": issue.status, "url": issue.url, "targets": targets}

    @app.post("/api/repos/{repo_id}/jira/issue/{key}/move")
    def jira_move(repo_id: int, key: str, body: JiraMoveBody) -> dict[str, str]:
        _, client = _jira_client(_repo_by_id(reg, repo_id))
        try:
            result = client.move(key, body.status)
        except jira.JiraError as exc:
            raise HTTPException(502, str(exc)) from exc
        if result == "no_transition":
            raise HTTPException(400, f"The workflow has no transition to {body.status!r}")
        return {"result": result}

    @app.delete("/api/repos/{repo_id}/inbox/{ticket_id}")
    def delete_inbox(repo_id: int, ticket_id: str) -> dict[str, bool]:
        _, inbox = _inbox(repo_id)
        return {"deleted": inbox.delete(ticket_id)}

    def _ticket_prompt(ticket_id: str, mode: str) -> str:
        if mode not in START_MODES:
            raise HTTPException(400, f"mode must be one of {START_MODES}")
        return f"/ccorch:ticket {ticket_id} {mode}".strip()

    @app.get("/api/repos/{repo_id}/inbox/{ticket_id}/command")
    def inbox_command(repo_id: int, ticket_id: str, mode: str = "") -> dict[str, str]:
        path = _repo_by_id(reg, repo_id)
        prompt = _ticket_prompt(ticket_id, mode)
        return {"slash": prompt, "shell": terminal.display_shell(path, prompt)}

    @app.post("/api/repos/{repo_id}/inbox/{ticket_id}/launch")
    def inbox_launch(repo_id: int, ticket_id: str, mode: str = "") -> dict[str, Any]:
        path, inbox = _inbox(repo_id)
        if inbox.get(ticket_id) is None:
            raise HTTPException(404, "ticket not in inbox")
        exe = claude.resolve()
        if exe is None:
            raise HTTPException(400, "claude not found")
        try:
            terminal.open_terminal(path, terminal.claude_argv(exe, _ticket_prompt(ticket_id, mode)))
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


def _spawn_detached(argv: list[str]) -> None:
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)


def _running_version(port: int) -> str | None:
    """Version of a ccorch settings page already on `port`, or None if nothing (ours) runs."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=1) as resp:
            meta = json.loads(resp.read())
    except (OSError, ValueError):
        return None
    if meta.get("app") != "ccorch-manager":
        return None
    return str(meta.get("version", "old"))


def _stop_running(port: int) -> None:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown", method="POST", headers={"X-CCorch": "1"}
    )
    # Old versions have no shutdown endpoint; the port check below reports that.
    with contextlib.suppress(OSError):
        urllib.request.urlopen(req, timeout=2).close()
    for _ in range(30):
        if _running_version(port) is None:
            return
        time.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser(description="ccorch manager UI")
    parser.add_argument("--port", type=int, default=7420)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    running = _running_version(args.port)
    if running == VERSION:
        print(f"ccorch manager already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    if running is not None:
        print(f"Replacing ccorch manager {running} with {VERSION}")
        _stop_running(args.port)
        if _running_version(args.port) is not None:
            sys.exit(
                f"An older ccorch manager is still running on port {args.port}; stop it "
                "(or restart your computer) and run /ccorch:manage again."
            )
    import uvicorn

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"ccorch manager at {url}  (Ctrl+C to stop)")
    uvicorn.run(
        create_app(Registry(registry_path()), args.port),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
