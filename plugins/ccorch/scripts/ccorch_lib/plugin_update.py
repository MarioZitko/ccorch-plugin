"""Installed vs. available ccorch version, and updating it, via the `claude plugin` CLI."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ccorch_lib.claude import _creationflags

PLUGIN_NAME = "ccorch"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]


class UpdateError(RuntimeError):
    pass


def running_from_cache(root: Path = PLUGIN_ROOT) -> bool:
    """True when this copy is an installed plugin (…/plugins/cache/<market>/<name>/<version>)."""
    return len(root.parents) > 2 and root.parents[2].name == "cache"


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:4])


def _cli(exe: str, *args: str, timeout: float = 120) -> str:
    try:
        proc = subprocess.run(
            [exe, "plugin", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"claude plugin {' '.join(args)}: {exc}") from exc
    if proc.returncode != 0:
        raise UpdateError((proc.stderr or proc.stdout).strip()[-600:] or "failed")
    return proc.stdout


def _json(exe: str, *args: str) -> Any:
    try:
        return json.loads(_cli(exe, *args))
    except json.JSONDecodeError as exc:
        raise UpdateError(f"unexpected output from claude plugin {' '.join(args)}") from exc


def _available_version(market_dir: Path) -> str | None:
    """Version of ccorch in the marketplace's local copy (as of its last refresh)."""
    try:
        catalog = json.loads(
            (market_dir / ".claude-plugin" / "marketplace.json").read_text("utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    for entry in catalog.get("plugins", []):
        if entry.get("name") != PLUGIN_NAME:
            continue
        source = entry.get("source")
        if isinstance(source, str):
            manifest = market_dir / source / ".claude-plugin" / "plugin.json"
            try:
                return str(json.loads(manifest.read_text("utf-8")).get("version"))
            except (OSError, json.JSONDecodeError):
                pass
        return str(entry["version"]) if entry.get("version") else None
    return None


def status(exe: str, running_version: str) -> dict[str, Any]:
    installed = next(
        (
            p
            for p in _json(exe, "list", "--json")
            if str(p.get("id", "")).startswith(f"{PLUGIN_NAME}@")
        ),
        None,
    )
    out: dict[str, Any] = {
        "running_version": running_version,
        "running_from": str(PLUGIN_ROOT),
        "dev_checkout": not running_from_cache(),
        "installed": installed is not None,
        "plugin_id": installed["id"] if installed else None,
        "installed_version": installed.get("version") if installed else None,
        "install_path": installed.get("installPath") if installed else None,
        "marketplace": None,
        "available_version": None,
        "update_available": False,
    }
    if installed is None:
        return out
    market = str(installed["id"]).split("@", 1)[1]
    out["marketplace"] = market
    for m in _json(exe, "marketplace", "list", "--json"):
        if m.get("name") == market and m.get("installLocation"):
            out["available_version"] = _available_version(Path(m["installLocation"]))
    if out["available_version"] and out["installed_version"]:
        out["update_available"] = version_key(out["available_version"]) > version_key(
            out["installed_version"]
        )
    return out


def refresh(exe: str, market: str) -> None:
    """Fetch the marketplace's latest catalog (git pull for GitHub/git sources)."""
    _cli(exe, "marketplace", "update", market, timeout=180)


def update(exe: str, plugin_id: str) -> str:
    return _cli(exe, "update", plugin_id, timeout=300).strip()
