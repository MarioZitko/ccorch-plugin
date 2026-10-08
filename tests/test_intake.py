"""Transcript intake with a fake `claude`, the inbox, and the inbox endpoints."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccorch_lib import claude, cli
from ccorch_lib.git import Git
from ccorch_lib.inbox import Inbox, InboxError
from ccorch_lib.state import StateStore
from server import Registry, create_app

H = {"X-CCorch": "1"}

FAKE = """#!{python}
import json, os, sys
prompt = sys.stdin.read()
args = sys.argv[1:]
notes = "key=%s tools=%s model=%s doc=%s" % (
    "ANTHROPIC_API_KEY" in os.environ, "--tools" in args,
    args[args.index("--model") + 1], "standup notes" in prompt)
print(json.dumps({{
    "type": "result", "subtype": "success", "is_error": False, "result": "done",
    "total_cost_usd": 0.0012, "duration_ms": 900, "modelUsage": {{"claude-haiku-test": {{}}}},
    "structured_output": {{"notes": notes, "tickets": [
        {{"external_id": "", "type": "bug", "title": "Fix login timeout",
          "description": "Users are logged out", "acceptance_criteria": ["stays logged in"],
          "size": "small"}},
        {{"external_id": "PRJ-9", "type": "feature", "title": "CSV export",
          "description": "", "acceptance_criteria": [], "size": "big"}}]}}}}))
"""


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(FAKE.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(claude, "resolve", lambda: str(exe))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    return exe


def test_ask_json_strips_api_key_and_disables_tools(fake_claude: Path, tmp_path: Path) -> None:
    answer = claude.ask_json("standup notes", {"type": "object"}, "haiku", tmp_path)
    assert answer.data["notes"] == "key=False tools=True model=haiku doc=True"
    assert answer.model == "claude-haiku-test" and answer.cost_usd == pytest.approx(0.0012)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-should-not-leak"  # only the child env


def test_extract_json_from_fenced_text() -> None:
    assert claude.extract_json('Here:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert claude.extract_json('sure {"a": 2}') == {"a": 2}


def test_inbox_ids_and_start(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inbox = Inbox(StateStore(Git(repo).git_dir()))
    assert inbox.next_ids("T", 2) == ["T-001", "T-002"]
    inbox.add(
        [{"id": "T-001", "type": "bug", "title": "  Fix  it ", "acceptance_criteria": "- a\n- b"}]
    )
    assert inbox.get("T-001")["title"] == "Fix it"  # type: ignore[index]
    assert inbox.get("T-001")["acceptance_criteria"] == ["a", "b"]  # type: ignore[index]
    assert inbox.next_ids("T", 1) == ["T-002"]
    with pytest.raises(InboxError):
        inbox.add(
            [{"id": "X", "type": "bug", "title": "a"}, {"id": "X", "type": "bug", "title": "b"}]
        )

    monkeypatch.chdir(repo)
    assert cli.main(["inbox", "show", "T-001"]) == 0
    assert "Title: Fix it" in capsys.readouterr().out
    assert (
        cli.main(["start", "--id", "T-001", "--type", "bug", "--title", "Fix it", "--no-fetch"])
        == 0
    )
    assert inbox.get("T-001")["status"] == "started"  # type: ignore[index]


def test_intake_endpoint_assigns_ids_and_saves(
    fake_claude: Path, repo: Path, tmp_path: Path
) -> None:
    client = TestClient(create_app(Registry(tmp_path / "home" / "manager.json")))
    client.post("/api/repos", json={"path": str(repo)}, headers=H)
    res = client.post("/api/repos/0/intake", json={"text": "standup notes ..."}, headers=H)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [t["id"] for t in body["tickets"]] == ["T-001", "PRJ-9"]
    assert body["model"] == "claude-haiku-test"

    saved = client.post("/api/repos/0/inbox", json={"tickets": body["tickets"]}, headers=H)
    assert saved.json() == {"saved": ["T-001", "PRJ-9"]}
    listed = client.get("/api/repos/0/inbox").json()
    assert {t["id"] for t in listed} == {"T-001", "PRJ-9"}
    cmd = client.get("/api/repos/0/inbox/T-001/command").json()
    assert cmd["slash"] == "/ccorch:ticket T-001"
    assert "--plugin-dir" in cmd["shell"]  # dev checkout -> loads the plugin explicitly
    quick = client.get("/api/repos/0/inbox/T-001/command", params={"mode": "quick"}).json()
    assert quick["slash"] == "/ccorch:ticket T-001 quick"
    assert client.get("/api/repos/0/inbox/T-001/command", params={"mode": "x"}).status_code == 400
    assert client.delete("/api/repos/0/inbox/PRJ-9", headers=H).json() == {"deleted": True}

    info = client.get("/api/claude").json()
    assert info["api_key_env"] is True and info["path"] == str(fake_claude)


def test_intake_rejects_empty(fake_claude: Path, repo: Path, tmp_path: Path) -> None:
    client = TestClient(create_app(Registry(tmp_path / "home" / "manager.json")))
    client.post("/api/repos", json={"path": str(repo)}, headers=H)
    res = client.post("/api/repos/0/intake", json={"text": "   "}, headers=H)
    assert res.status_code == 502 and "empty" in json.loads(res.text)["detail"]
