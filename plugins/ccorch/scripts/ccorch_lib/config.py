"""Per-repo settings: `.claude/ccorch.toml` (committed) + `.claude/ccorch.local.toml` (personal).

The local file is deep-merged over the shared one, and both over DEFAULTS. Stdlib only.
"""

from __future__ import annotations

import copy
import json
import re
import tomllib
from pathlib import Path
from typing import Any

CONFIG_REL = Path(".claude") / "ccorch.toml"
LOCAL_CONFIG_REL = Path(".claude") / "ccorch.local.toml"

TICKET_TYPES = ("feature", "bug", "task")
# Aliases resolve to the newest model the installed `claude` CLI knows - keep the CLI updated.
MODEL_CHOICES = ("opus", "sonnet", "haiku", "inherit")

DEFAULTS: dict[str, Any] = {
    "repo": {
        "base_branch": "main",
        "remote": "origin",
    },
    "branch": {
        "template": "{type}/{ticket_id}-{slug}",
        "slug_max_len": 40,
        "type_prefix": {"feature": "feature", "bug": "fix", "task": "chore"},
    },
    "gate": {
        "build": [],
        "test": [],
        "timeout_s": 1800,
        "max_attempts": 3,
    },
    "commit": {
        "phase_message": "[{ticket_id}] phase {index}: {title}",
        "fix_message": "[{ticket_id}] review fixes ({iteration})",
        "single_message": "[{ticket_id}] {title}",
    },
    "mr": {
        "target": "",
        "title": "{ticket_id}: {title}",
        "remove_source_branch": True,
        "squash": False,
        "draft": False,
        "auto_merge": False,
        "labels": [],
        "assignee": "",
    },
    "workflow": {
        "planning": "auto",
        "plan_approval": True,
        "review": True,
        "review_quick": True,
        "max_fix_iterations": 2,
        "small_inline": True,
        "small_review_max_lines": 150,
    },
    "intake": {
        "id_prefix": "T",
    },
    "models": {
        "intake": "haiku",
        "planner": "opus",
        "implementer": "sonnet",
        "reviewer": "opus",
        "reviewer_small": "sonnet",
    },
}

MODEL_ROLES = ("intake", "planner", "implementer", "reviewer", "reviewer_small")
PLANNING_CHOICES = ("auto", "always", "never")
_ID_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_BRANCH_FIELDS = {"type", "ticket_id", "slug"}
_COMMIT_FIELDS = {"ticket_id", "title", "index", "iteration", "type", "branch"}
_MR_FIELDS = {"ticket_id", "title", "type", "branch"}


class ConfigError(ValueError):
    """The config file is unreadable or a value has the wrong type/shape."""


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load(repo: Path) -> dict[str, Any]:
    """Merged, validated config for `repo` (DEFAULTS < ccorch.toml < ccorch.local.toml)."""
    shared = read_toml(repo / CONFIG_REL)
    local = read_toml(repo / LOCAL_CONFIG_REL)
    cfg = deep_merge(deep_merge(DEFAULTS, shared), local)
    validate(cfg)
    return cfg


def has_config(repo: Path) -> bool:
    return (repo / CONFIG_REL).is_file()


def _expect(cond: bool, msg: str, errors: list[str]) -> None:
    if not cond:
        errors.append(msg)


def _check_template(value: object, allowed: set[str], where: str, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{where} must be a string")
        return
    unknown = {m for m in _PLACEHOLDER.findall(value) if m not in allowed}
    if unknown:
        errors.append(
            f"{where}: unknown placeholder(s) {sorted(unknown)}; allowed {sorted(allowed)}"
        )


def _str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def validate(cfg: dict[str, Any]) -> None:
    """Raise ConfigError listing every problem (types, placeholders, enums)."""
    errors: list[str] = []
    repo, branch, gate = cfg["repo"], cfg["branch"], cfg["gate"]
    commit, mr, wf = cfg["commit"], cfg["mr"], cfg["workflow"]

    for key in ("base_branch", "remote"):
        _expect(
            isinstance(repo[key], str) and repo[key].strip() != "",
            f"repo.{key} is required",
            errors,
        )

    _check_template(branch["template"], _BRANCH_FIELDS, "branch.template", errors)
    if isinstance(branch["template"], str) and "{ticket_id}" not in branch["template"]:
        errors.append("branch.template must contain {ticket_id}")
    _expect(
        isinstance(branch["slug_max_len"], int) and 5 <= branch["slug_max_len"] <= 100,
        "branch.slug_max_len must be an integer between 5 and 100",
        errors,
    )
    prefixes = branch["type_prefix"]
    if not isinstance(prefixes, dict):
        errors.append("branch.type_prefix must be a table")
    else:
        for t in TICKET_TYPES:
            _expect(
                isinstance(prefixes.get(t), str), f"branch.type_prefix.{t} must be a string", errors
            )

    for key in ("build", "test"):
        _expect(_str_list(gate[key]), f"gate.{key} must be a list of command strings", errors)
    _expect(
        isinstance(gate["timeout_s"], int) and gate["timeout_s"] > 0,
        "gate.timeout_s must be > 0",
        errors,
    )
    _expect(
        isinstance(gate["max_attempts"], int) and 1 <= gate["max_attempts"] <= 8,
        "gate.max_attempts must be between 1 and 8",
        errors,
    )

    for key in ("phase_message", "fix_message", "single_message"):
        _check_template(commit[key], _COMMIT_FIELDS, f"commit.{key}", errors)

    _check_template(mr["title"], _MR_FIELDS, "mr.title", errors)
    _expect(isinstance(mr["target"], str), "mr.target must be a string", errors)
    for key in ("remove_source_branch", "squash", "draft", "auto_merge"):
        _expect(isinstance(mr[key], bool), f"mr.{key} must be true/false", errors)
    _expect(_str_list(mr["labels"]), "mr.labels must be a list of strings", errors)
    _expect(isinstance(mr["assignee"], str), "mr.assignee must be a string", errors)

    _expect(
        wf["planning"] in PLANNING_CHOICES,
        f"workflow.planning must be one of {PLANNING_CHOICES}",
        errors,
    )
    for key in ("plan_approval", "review", "review_quick", "small_inline"):
        _expect(isinstance(wf[key], bool), f"workflow.{key} must be true/false", errors)
    _expect(
        isinstance(wf["max_fix_iterations"], int) and 0 <= wf["max_fix_iterations"] <= 5,
        "workflow.max_fix_iterations must be between 0 and 5",
        errors,
    )

    _expect(
        isinstance(wf["small_review_max_lines"], int)
        and not isinstance(wf["small_review_max_lines"], bool)
        and 0 <= wf["small_review_max_lines"] <= 5000,
        "workflow.small_review_max_lines must be between 0 and 5000",
        errors,
    )

    for role in MODEL_ROLES:
        _expect(
            cfg["models"].get(role) in MODEL_CHOICES,
            f"models.{role} must be one of {MODEL_CHOICES}",
            errors,
        )
    prefix = cfg["intake"]["id_prefix"]
    _expect(
        isinstance(prefix, str) and bool(_ID_PREFIX.match(prefix)),
        "intake.id_prefix must start with a letter (letters, digits, - or _; max 16)",
        errors,
    )

    if errors:
        raise ConfigError("; ".join(errors))


def mr_target(cfg: dict[str, Any]) -> str:
    return str(cfg["mr"]["target"] or cfg["repo"]["base_branch"])


# --- TOML writing (only the shapes this config uses: str, bool, int, list[str], nested tables)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise ConfigError(f"cannot write {type(value).__name__} to TOML")


_HEADER = """\
# ccorch settings for this repository (shared with the team - commit this file).
# Edit with /ccorch:manage, or by hand. Personal overrides go in .claude/ccorch.local.toml.
"""


def dumps(cfg: dict[str, Any], header: str = _HEADER) -> str:
    lines = [header.rstrip("\n")]

    def emit(table: dict[str, Any], prefix: str) -> None:
        scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
        subs = {k: v for k, v in table.items() if isinstance(v, dict)}
        if scalars or not subs:
            lines.append("")
            lines.append(f"[{prefix}]")
            for key, value in scalars.items():
                lines.append(f"{key} = {_toml_value(value)}")
        for key, sub in subs.items():
            emit(sub, f"{prefix}.{key}")

    for section, table in cfg.items():
        emit(table, section)
    return "\n".join(lines) + "\n"


def write(repo: Path, cfg: dict[str, Any]) -> Path:
    validate(deep_merge(DEFAULTS, cfg))
    path = repo / CONFIG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(cfg), encoding="utf-8", newline="\n")
    return path
