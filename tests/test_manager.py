from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import Registry, create_app

H = {"X-CCorch": "1"}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Registry(tmp_path / "home" / "manager.json")))


def test_mutations_need_header_and_local_host(client: TestClient, repo: Path) -> None:
    assert client.post("/api/repos", json={"path": str(repo)}).status_code == 403
    assert client.get("/api/meta", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/api/meta").json()["app"] == "ccorch-manager"


def test_configure_and_install_repo(client: TestClient, repo: Path) -> None:
    (repo / "App.sln").write_text("")
    (repo / "src").mkdir()
    added = client.post("/api/repos", json={"path": str(repo / "src")}, headers=H)
    assert added.status_code == 200, added.text
    assert added.json()["has_config"] is False

    cfg = client.get("/api/repos/0/config").json()
    assert cfg["has_file"] is False
    assert cfg["config"]["gate"]["build"] == ["dotnet build"]
    assert cfg["config"]["repo"]["base_branch"] == "main"

    edited = cfg["config"]
    edited["branch"]["template"] = "{ticket_id}/{slug}"
    bad = {**edited, "mr": {**edited["mr"], "title": "{nope}"}}
    assert client.post("/api/repos/0/validate", json={"config": bad}, headers=H).json()["errors"]

    client.put(
        "/api/marketplace",
        json={"name": "ccorch-tools", "url": "https://gitlab.example.com/t/ccorch-plugin.git"},
        headers=H,
    )
    planned = client.post("/api/repos/0/plan", json={"config": edited}, headers=H).json()
    assert {c["path"] for c in planned["changes"]} == {
        ".claude/ccorch.toml",
        ".claude/settings.json",
        ".gitignore",
    }

    applied = client.post(
        "/api/repos/0/apply", json={"config": edited, "commit": True}, headers=H
    ).json()
    assert applied["commit"]
    settings = json.loads((repo / ".claude/settings.json").read_text())
    assert settings["enabledPlugins"] == {"ccorch@ccorch-tools": True}

    summary = client.get("/api/repos").json()[0]
    assert summary["has_config"] and summary["plugin_enabled"]
    again = client.get("/api/repos/0/config").json()
    assert again["has_file"] and again["config"]["branch"]["template"] == "{ticket_id}/{slug}"


def test_branch_preview(client: TestClient) -> None:
    out = client.post(
        "/api/preview/branch",
        headers=H,
        json={
            "branch": {"template": "{type}/{ticket_id}-{slug}", "type_prefix": {"bug": "hotfix"}},
            "type": "bug",
            "ticket_id": "PRJ-9",
            "title": "Pucanje kod plaćanja",
        },
    ).json()
    assert out == {"name": "hotfix/PRJ-9-pucanje-kod-placanja", "error": None}


def test_gate_runs_commands(client: TestClient, repo: Path) -> None:
    client.post("/api/repos", json={"path": str(repo)}, headers=H)
    gate = {"build": ["git status"], "test": ["false"]}
    res = client.post("/api/repos/0/test-gate", headers=H, json={"config": {"gate": gate}}).json()
    assert res["passed"] is False and res["command"] == "false"


def test_browse_lists_git_dirs(client: TestClient, repo: Path) -> None:
    listing = client.get("/api/fs", params={"path": str(repo.parent)}).json()
    assert any(e["name"] == "work" and e["is_git"] for e in listing["entries"])


def test_meta_reports_plugin_version(client: TestClient) -> None:
    from server import VERSION

    assert client.get("/api/meta").json()["version"] == VERSION != "dev"
    assert client.post("/api/shutdown").status_code == 403  # needs the X-CCorch header
