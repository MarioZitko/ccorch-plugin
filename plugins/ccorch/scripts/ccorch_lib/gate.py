"""Build/test gate: run each configured command, stop at the first failure, keep the output tail.

Ported from ccorch `adapters/gate_subprocess.py` (without the cancel token: a hook or CLI call is
cancelled by killing the whole process).
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

TAIL_LINES = 200
_NOT_RUNNABLE = 127


@dataclass
class GateResult:
    passed: bool
    exit_code: int
    output_tail: str
    command: str = ""
    skipped: bool = False


def split_command(command: str) -> list[str]:
    """Split a command string into argv. On Windows backslashes are kept literally."""
    argv = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'" else a for a in argv]
    return argv


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def run_one(command: str, cwd: Path, timeout_s: float) -> GateResult:
    try:
        argv = split_command(command)
    except ValueError as exc:
        return GateResult(False, _NOT_RUNNABLE, f"cannot parse command: {exc}", command)
    if not argv:
        return GateResult(True, 0, "", command)
    exe = shutil.which(argv[0], path=None)
    if exe is None:
        return GateResult(False, _NOT_RUNNABLE, f"executable not found: {argv[0]}", command)
    argv[0] = exe
    kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,  # type: ignore[call-overload]
        )
    except OSError as exc:
        return GateResult(False, _NOT_RUNNABLE, f"cannot start command: {exc}", command)

    tail: deque[str] = deque(maxlen=TAIL_LINES)
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        tail.extend(out.splitlines())
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, _ = proc.communicate()
        tail.extend((out or "").splitlines())
        tail.append(f"[gate] timed out after {timeout_s:g}s; process tree killed")
        return GateResult(False, proc.returncode or -1, "\n".join(tail), command)
    return GateResult(proc.returncode == 0, proc.returncode, "\n".join(tail), command)


def run(build: list[str], test: list[str], cwd: Path, timeout_s: float) -> GateResult:
    commands = [c for c in [*build, *test] if c.strip()]
    if not commands:
        return GateResult(True, 0, "no build/test commands configured", skipped=True)
    last = GateResult(True, 0, "")
    for command in commands:
        last = run_one(command, cwd, timeout_s)
        if not last.passed:
            return last
    return last


def tail(text: str, lines: int) -> str:
    return "\n".join(text.splitlines()[-lines:])
