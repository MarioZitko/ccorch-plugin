from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from ccorch_lib import branch, config, install, mr


def test_slugify_transliterates_croatian() -> None:
    assert branch.slugify("Čišćenje Žute đačke liste!") == "ciscenje-zute-dacke-liste"


def test_render_uses_type_prefix_and_collapses() -> None:
    name = branch.render(
        "{type}/{ticket_id}-{slug}", "bug", " ABC 12 ", "Fix  login", {"bug": "fix"}
    )
    assert name == "fix/ABC-12-fix-login"


def test_render_rejects_unknown_placeholder() -> None:
    with pytest.raises(branch.BranchNameError):
        branch.render("{type}/{nope}", "bug", "A-1", "x")


def test_defaults_are_valid_and_toml_roundtrips() -> None:
    config.validate(config.DEFAULTS)
    text = config.dumps(config.DEFAULTS)
    assert tomllib.loads(text) == config.DEFAULTS


def test_local_file_overrides_shared(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/ccorch.toml").write_text('[repo]\nbase_branch = "develop"\n')
    (tmp_path / ".claude/ccorch.local.toml").write_text('[models]\nplanner = "sonnet"\n')
    cfg = config.load(tmp_path)
    assert cfg["repo"]["base_branch"] == "develop"
    assert cfg["models"]["planner"] == "sonnet"
    assert cfg["models"]["reviewer"] == "opus"


def test_validation_lists_problems() -> None:
    bad = config.deep_merge(
        config.DEFAULTS,
        {
            "branch": {"template": "{type}/{slug}"},
            "mr": {"title": "{oops}", "draft": "yes"},
            "models": {"planner": "gpt", "reviewer_small": "big"},
            "workflow": {"planning": "sometimes", "small_review_max_lines": 9999},
        },
    )
    with pytest.raises(config.ConfigError) as err:
        config.validate(bad)
    msg = str(err.value)
    for fragment in (
        "{ticket_id}",
        "mr.title",
        "mr.draft",
        "models.planner",
        "workflow.planning",
        "models.reviewer_small",
        "small_review_max_lines",
    ):
        assert fragment in msg


def test_push_options() -> None:
    cfg = config.deep_merge(
        config.DEFAULTS,
        {
            "repo": {"base_branch": "develop"},
            "mr": {"draft": True, "labels": ["ai", " "], "assignee": "mario", "squash": True},
        },
    )
    opts = mr.push_options(cfg, title="ABC-1: Add x", description="line one\nline two")
    assert opts[:3] == [
        "merge_request.create",
        "merge_request.target=develop",
        "merge_request.title=ABC-1: Add x",
    ]
    assert "merge_request.description=line one · line two" in opts
    assert {
        "merge_request.draft",
        "merge_request.squash",
        "merge_request.remove_source_branch",
        "merge_request.label=ai",
        "merge_request.assign=mario",
    } <= set(opts)
    assert all("\n" not in o for o in opts)


def test_detect_commands(tmp_path: Path) -> None:
    (tmp_path / "App.sln").write_text("")
    assert install.detect_commands(tmp_path) == (["dotnet build"], ["dotnet test --no-build"])
    other = tmp_path / "web"
    other.mkdir()
    (other / "package.json").write_text(
        json.dumps({"scripts": {"build": "vite build", "test": "vitest"}})
    )
    (other / "pnpm-lock.yaml").write_text("")
    assert install.detect_commands(other) == (["pnpm run build"], ["pnpm test"])


def test_merged_settings_keeps_other_keys() -> None:
    old = json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "enabledPlugins": {"x@y": True}})
    market = install.Marketplace("ccorch-tools", "https://gitlab.example.com/t/ccorch-plugin.git")
    data = json.loads(install.merged_settings(old, market))
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    assert data["enabledPlugins"] == {"x@y": True, "ccorch@ccorch-tools": True}
    assert data["extraKnownMarketplaces"]["ccorch-tools"]["source"]["url"].endswith(".git")


def test_install_plan_is_idempotent(repo: Path) -> None:
    cfg = install.detect_defaults(repo)
    market = install.Marketplace("ccorch-tools", "https://gitlab.example.com/t/ccorch-plugin.git")
    changes = install.plan(repo, cfg, market)
    assert {c.path for c in changes} == {
        ".claude/ccorch.toml",
        ".claude/settings.json",
        ".gitignore",
    }
    install.apply(repo, changes)
    assert install.plan(repo, cfg, market) == []
    assert config.load(repo)["repo"]["base_branch"] == "main"
