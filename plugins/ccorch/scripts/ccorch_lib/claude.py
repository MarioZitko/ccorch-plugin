"""Run the local `claude` CLI headless for one-shot, tool-less calls (e.g. transcript intake).

It uses whatever account Claude Code is logged into (your subscription). ANTHROPIC_API_KEY is
removed from the child environment so a stray key never switches billing to the API.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BILLING_ENV = ("ANTHROPIC_API_KEY",)
_FENCE = re.compile(r"```json[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


class ClaudeError(RuntimeError):
    pass


def _creationflags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def resolve() -> str | None:
    """Path of the `claude` executable. Also checks install locations shells alias to."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [
        home / ".claude" / "local" / "claude",
        home / ".local" / "bin" / "claude",
        home / ".local" / "bin" / "claude.exe",
        Path(os.environ.get("APPDATA", home)) / "npm" / "claude.cmd",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ]
    return next((str(p) for p in candidates if p.is_file()), None)


def child_env() -> tuple[dict[str, str], list[str]]:
    env = dict(os.environ)
    removed = [k for k in BILLING_ENV if env.pop(k, None) is not None]
    return env, removed


def version(exe: str) -> str:
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable ({exc})"
    return (proc.stdout or proc.stderr).strip()


def update(exe: str) -> str:
    proc = subprocess.run(
        [exe, "update"],
        capture_output=True,
        text=True,
        timeout=600,
        stdin=subprocess.DEVNULL,
        creationflags=_creationflags(),
    )
    return (proc.stdout + proc.stderr).strip()


@dataclass
class JsonAnswer:
    data: Any
    cost_usd: float
    duration_ms: int
    model: str


def extract_json(text: str) -> Any:
    blocks = _FENCE.findall(text)
    candidate = (blocks[-1] if blocks else text).strip()
    if not blocks and not candidate.startswith(("{", "[")):
        start = min((i for i in (candidate.find("{"), candidate.find("[")) if i >= 0), default=-1)
        candidate = candidate[start:] if start >= 0 else candidate
    return json.loads(candidate)


def ask_json(
    prompt: str, schema: dict[str, Any], model: str, cwd: Path, timeout_s: float = 300
) -> JsonAnswer:
    """One tool-less headless call that must answer with JSON matching `schema`."""
    exe = resolve()
    if exe is None:
        raise ClaudeError("`claude` not found - install Claude Code and log in")
    batch_shim = exe.lower().endswith((".cmd", ".bat"))
    argv = [
        exe,
        "-p",
        *([] if model == "inherit" else ["--model", model]),  # inherit = your default model
        "--output-format",
        "json",
        "--max-turns",
        "3",
        "--strict-mcp-config",
        "--no-session-persistence",
    ]
    if batch_shim:
        # cmd.exe would mangle an empty arg and JSON quotes; deny tools by name instead.
        argv += [
            "--disallowedTools",
            "Bash",
            "Edit",
            "Write",
            "Read",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "NotebookEdit",
            "Task",
            "Agent",
        ]
    else:
        argv += ["--tools", "", "--json-schema", json.dumps(schema)]
    env, _ = child_env()
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=env,
            timeout=timeout_s,
            creationflags=_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeError(f"claude timed out after {timeout_s:g}s") from exc
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeError((proc.stderr or proc.stdout).strip()[-800:] or "no output") from exc
    if not isinstance(result, dict):
        raise ClaudeError("unexpected claude output")
    if result.get("is_error") or proc.returncode != 0:
        raise ClaudeError(str(result.get("result") or proc.stderr).strip()[-800:])
    data = result.get("structured_output")
    if data is None:
        try:
            data = extract_json(str(result.get("result", "")))
        except json.JSONDecodeError as exc:
            raise ClaudeError(f"answer was not valid JSON: {exc}") from exc
    used = result.get("modelUsage")
    fallback = "default" if model == "inherit" else model
    model_used = ", ".join(used) if isinstance(used, dict) and used else fallback
    return JsonAnswer(
        data=data,
        cost_usd=float(result.get("total_cost_usd") or 0.0),
        duration_ms=int(result.get("duration_ms") or 0),
        model=model_used,
    )
