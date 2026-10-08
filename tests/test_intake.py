"""Transcript intake with a fake `claude`, the inbox, and the inbox endpoints."""

from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccorch_lib import claude, cli, terminal
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
    args[args.index("--model") + 1] if "--model" in args else "none", "standup notes" in prompt)
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


def test_ask_json_inherit_sends_no_model(fake_claude: Path, tmp_path: Path) -> None:
    answer = claude.ask_json("standup notes", {"type": "object"}, "inherit", tmp_path)
    assert "model=none" in answer.data["notes"]


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


def test_display_shell_quotes_paths_with_spaces() -> None:
    path = Path("/tmp/my repo/it's here")
    parts = shlex.split(terminal.display_shell(path, "/ccorch:ticket T-1"))
    assert parts[:3] == ["cd", str(path), "&&"] and parts[-1] == "/ccorch:ticket T-1"


def test_inbox_add_refuses_to_overwrite_started_ticket(repo: Path) -> None:
    inbox = Inbox(StateStore(Git(repo).git_dir()))
    inbox.add([{"id": "T-001", "type": "bug", "title": "a"}])
    inbox.add([{"id": "T-001", "type": "bug", "title": "a2"}])  # still queued: fine
    inbox.mark_started("T-001", "fix/T-001-a")
    with pytest.raises(InboxError, match="already started on fix/T-001-a"):
        inbox.add(
            [
                {"id": "T-002", "type": "bug", "title": "b"},
                {"id": "T-001", "type": "bug", "title": "c"},
            ]
        )
    assert inbox.get("T-002") is None  # the batch failed as a whole
    started = inbox.get("T-001")
    assert started is not None and started["branch"] == "fix/T-001-a" and started["title"] == "a2"


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
    assert shlex.split(cmd["shell"])[:3] == ["cd", str(repo), "&&"]
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
