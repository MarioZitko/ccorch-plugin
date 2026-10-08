"""Detect sensible defaults for a repo and compute/apply the files that install ccorch into it."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ccorch_lib import config
from ccorch_lib.git import Git

PLUGIN_NAME = "ccorch"
SETTINGS_REL = Path(".claude") / "settings.json"
GITIGNORE_LINE = ".claude/ccorch.local.toml"


@dataclass
class Marketplace:
    name: str
    url: str
    ref: str = "main"

    @property
    def plugin_id(self) -> str:
        return f"{PLUGIN_NAME}@{self.name}"


@dataclass
class FileChange:
    path: str  # relative to the repo root
    old: str | None  # None = file does not exist yet
    new: str

    @property
    def changed(self) -> bool:
        return self.old != self.new


def _first(root: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        found = sorted(root.glob(pattern))
        if found:
            return found[0]
    return None


def detect_commands(root: Path) -> tuple[list[str], list[str]]:
    """Guess build/test commands from the files in the repo root."""
    if _first(root, ["*.sln", "*.slnx", "*.csproj", "*/*.sln", "*/*.csproj"]):
        return ["dotnet build"], ["dotnet test --no-build"]
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
        except (json.JSONDecodeError, OSError):
            scripts = {}
        runner = "npm"
        if (root / "pnpm-lock.yaml").is_file():
            runner = "pnpm"
        elif (root / "yarn.lock").is_file():
            runner = "yarn"
        build = [f"{runner} run build"] if "build" in scripts else []
        test_script = str(scripts.get("test", ""))
        test = [f"{runner} test"] if test_script and "no test specified" not in test_script else []
        return build, test
    if (root / "pyproject.toml").is_file():
        return [], ["uv run pytest" if (root / "uv.lock").is_file() else "pytest"]
    if (root / "go.mod").is_file():
        return ["go build ./..."], ["go test ./..."]
    if (root / "Cargo.toml").is_file():
        return ["cargo build"], ["cargo test"]
    if (root / "pom.xml").is_file():
        return ["mvn -q -DskipTests package"], ["mvn -q test"]
    if _first(root, ["build.gradle", "build.gradle.kts"]):
        wrapper = "./gradlew" if (root / "gradlew").is_file() else "gradle"
        return [f"{wrapper} build -x test"], [f"{wrapper} test"]
    return [], []


def detect_defaults(root: Path) -> dict[str, Any]:
    """DEFAULTS adjusted for this repo: base branch from origin/HEAD, build/test from files."""
    cfg = copy.deepcopy(config.DEFAULTS)
    git = Git(root)
    base = None
    if git.has_remote():
        base = git.remote_default_branch()
    if not base:
        current = git.current_branch()
        base = current if current in ("main", "master", "develop", "dev") else "main"
    cfg["repo"]["base_branch"] = base
    cfg["gate"]["build"], cfg["gate"]["test"] = detect_commands(root)
    return cfg


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def merged_settings(old_text: str | None, market: Marketplace) -> str:
    """`.claude/settings.json` with the marketplace registered and the plugin enabled.

    Every other key is preserved. Raises ValueError if the existing file is not a JSON object.
    """
    data: dict[str, Any] = {}
    if old_text and old_text.strip():
        loaded = json.loads(old_text)
        if not isinstance(loaded, dict):
            raise ValueError(".claude/settings.json is not a JSON object")
        data = loaded
    markets = data.setdefault("extraKnownMarketplaces", {})
    markets[market.name] = {"source": {"source": "git", "url": market.url, "ref": market.ref}}
    data.setdefault("enabledPlugins", {})[market.plugin_id] = True
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def plan(root: Path, cfg: dict[str, Any], market: Marketplace | None) -> list[FileChange]:
    """Files to write. `cfg` is the full config as edited in the UI (validated here)."""
    config.validate(config.deep_merge(config.DEFAULTS, cfg))
    changes = [
        FileChange(
            str(config.CONFIG_REL).replace("\\", "/"),
            _read(root / config.CONFIG_REL),
            config.dumps(cfg),
        ),
    ]
    if market is not None and market.url.strip():
        old = _read(root / SETTINGS_REL)
        changes.append(FileChange(".claude/settings.json", old, merged_settings(old, market)))
    gitignore_old = _read(root / ".gitignore")
    lines = (gitignore_old or "").splitlines()
    if GITIGNORE_LINE not in (line.strip() for line in lines):
        prefix = gitignore_old or ""
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        changes.append(FileChange(".gitignore", gitignore_old, f"{prefix}{GITIGNORE_LINE}\n"))
    return [c for c in changes if c.changed]


def apply(root: Path, changes: list[FileChange]) -> list[str]:
    written = []
    for change in changes:
        target = root / change.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.new, encoding="utf-8", newline="\n")
        written.append(change.path)
    return written


def install_status(root: Path, market_name: str | None) -> dict[str, Any]:
    settings_text = _read(root / SETTINGS_REL)
    enabled = False
    if settings_text and market_name:
        try:
            enabled = bool(
                json.loads(settings_text)
                .get("enabledPlugins", {})
                .get(f"{PLUGIN_NAME}@{market_name}")
            )
        except (json.JSONDecodeError, AttributeError):
            enabled = False
    return {"has_config": config.has_config(root), "plugin_enabled": enabled}
