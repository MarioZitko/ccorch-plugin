"""Open an interactive Claude Code session in a new terminal window, already running a command."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


class TerminalError(RuntimeError):
    pass


def plugin_installed() -> bool:
    """True when this copy runs from Claude Code's plugin cache (not a dev checkout)."""
    return (Path.home() / ".claude" / "plugins") in PLUGIN_ROOT.parents


def claude_argv(exe: str, prompt: str) -> list[str]:
    argv = [exe]
    if not plugin_installed():
        argv += ["--plugin-dir", str(PLUGIN_ROOT)]
    return [*argv, prompt]


def display_command(prompt: str) -> str:
    """What to type yourself, for the copy button."""
    parts = ["claude"]
    if not plugin_installed():
        parts += ["--plugin-dir", str(PLUGIN_ROOT)]
    return " ".join(shlex.quote(p) for p in [*parts, prompt])


def _applescript_str(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_terminal(cwd: Path, argv: list[str]) -> None:
    if sys.platform == "darwin":
        shell = f"cd {shlex.quote(str(cwd))} && " + " ".join(shlex.quote(a) for a in argv)
        script = [
            "-e",
            'tell application "Terminal"',
            "-e",
            "activate",
            "-e",
            f"do script {_applescript_str(shell)}",
            "-e",
            "end tell",
        ]
        proc = subprocess.run(["osascript", *script], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise TerminalError(proc.stderr.strip() or "osascript failed")
        return
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_CONSOLE
        if shutil.which("wt"):
            subprocess.Popen(["wt", "-d", str(cwd), *argv], creationflags=flags)
        else:
            subprocess.Popen(["cmd", "/k", *argv], cwd=cwd, creationflags=flags)
        return
    for term, prefix in (
        ("x-terminal-emulator", ["-e"]),
        ("gnome-terminal", ["--"]),
        ("konsole", ["-e"]),
    ):
        if shutil.which(term):
            subprocess.Popen([term, *prefix, *argv], cwd=cwd, start_new_session=True)
            return
    raise TerminalError("no terminal emulator found; copy the command instead")
