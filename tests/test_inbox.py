"""Editing inbox tickets: update rules, `ccorch ticket-check`, the PUT endpoint, Jira sync."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccorch_lib import cli, config, jira
from ccorch_lib.git import Git
from ccorch_lib.inbox import Inbox, InboxError
from ccorch_lib.state import StateStore
from server import Registry, create_app
from tests.conftest import git
from tests.fake_jira import FakeJira

H = {"X-CCorch": "1"}


def ticket(tid: str = "T-001", **over: object) -> dict[str, object]:
    return {"id": tid, "type": "task", "title": "Old title", "acceptance_criteria": ["a"], **over}


def inbox_of(repo: Path) -> Inbox:
    return Inbox(StateStore(Git(repo).git_dir()))


@pytest.fixture
def configured(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config.write(repo, config.DEFAULTS)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "ccorch config")
    git(repo, "push")
    monkeypatch.chdir(repo)
    return repo


# --- Inbox.update -----------------------------------------------------------------------------


def test_update_adds_revisions_and_history(repo: Path) -> None:
    inbox = inbox_of(repo)
    inbox.add([ticket()])
    assert inbox.get("T-001")["revision"] == 1  # type: ignore[index]
    same = inbox.update("T-001", {"title": "Old title"})
    assert same["revision"] == 1 and "history" not in same
    rec = inbox.update("T-001", {"title": "New title", "acceptance_criteria": ["a", "b"]})
    assert rec["revision"] == 2 and rec["title"] == "New title" and rec["updated_at"]
    assert rec["history"][0]["title"] == "Old title" and rec["history"][0]["revision"] == 1
    for i in range(12):
        rec = inbox.update("T-001", {"description": f"d{i}"})
    assert len(rec["history"]) == 10 and rec["revision"] == 14
    # Old records without a revision count as revision 1.
    old = inbox.get("T-001") or {}
    del old["revision"], old["history"]
    inbox._write(old)
    assert inbox.update("T-001", {"title": "x"})["revision"] == 2


def test_update_id_rules(repo: Path) -> None:
    inbox = inbox_of(repo)
    inbox.add([ticket("T-001"), ticket("T-002")])
    with pytest.raises(InboxError, match="already in the inbox"):
        inbox.update("T-001", {"id": "T-002"})
    renamed = inbox.update("T-001", {"id": "T-009"})
    assert renamed["id"] == "T-009" and inbox.get("T-001") is None
    inbox.mark_started("T-009", "task/T-009-x")
    with pytest.raises(InboxError, match="locked"):
        inbox.update("T-009", {"id": "T-010"})
    started = inbox.update("T-009", {"title": "Edited after start"})
    assert started["status"] == "started" and started["branch"] == "task/T-009-x"
    with pytest.raises(InboxError, match="not in the inbox"):
        inbox.update("T-404", {"title": "x"})
    with pytest.raises(InboxError, match="title is required"):
        inbox.update("T-002", {"title": "  "})


def test_finished_tickets_are_still_editable(repo: Path) -> None:
    inbox = inbox_of(repo)
    inbox.add([ticket()])
    inbox.mark_finished("T-001", "done", "https://gitlab.example.com/mr/1")
    rec = inbox.update("T-001", {"title": "Late edit"})
    assert rec["status"] == "done" and rec["mr_url"].endswith("/mr/1") and rec["revision"] == 2


# --- ccorch ticket-check ----------------------------------------------------------------------


def test_ticket_check_flow(configured: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = configured
    inbox = inbox_of(repo)
    inbox.add([ticket()])
    assert cli.main(["start", "--id", "T-001", "--type", "task", "--title", "Old title"]) == 0
    capsys.readouterr()
    assert cli.main(["ticket-check"]) == 0
    assert capsys.readouterr().out.strip() == "Ticket unchanged."
    cli.main(["context"])
    assert "TICKET UPDATED" not in capsys.readouterr().out

    inbox.update("T-001", {"title": "Better title", "acceptance_criteria": ["a", "b"]})
    cli.main(["context"])
    assert "run `ccorch ticket-check`" in capsys.readouterr().out
    assert cli.main(["ticket-check"]) == 0
    out = capsys.readouterr().out
    assert "TICKET UPDATED (revision 2" in out
    assert "Changed: title, acceptance criteria" in out
    assert "Title: Better title" in out and "- b" in out
    assert cli.main(["ticket-check"]) == 0
    assert capsys.readouterr().out.strip() == "Ticket unchanged."
    cli.main(["context"])
    assert "TICKET UPDATED" not in capsys.readouterr().out

    # The new title is used for the commit and the MR; the branch name stays.
    (repo / "x.txt").write_text("x\n")
    assert cli.main(["commit", "--no-gate"]) == 0
    assert "Better title" in git(repo, "log", "-1", "--format=%s")
    capsys.readouterr()
    assert cli.main(["mr", "--dry-run"]) == 0
    assert "Better title" in capsys.readouterr().out
    assert git(repo, "branch", "--show-current").strip().endswith("/T-001-old-title")

    assert cli.main(["mr"]) == 0
    done = inbox.get("T-001") or {}
    assert done["status"] == "done"


def test_finish_marks_inbox_abandoned(configured: Path) -> None:
    inbox = inbox_of(configured)
    inbox.add([ticket()])
    assert cli.main(["start", "--id", "T-001", "--type", "task", "--title", "t"]) == 0
    assert cli.main(["finish", "--outcome", "abandoned"]) == 0
    assert (inbox.get("T-001") or {})["status"] == "abandoned"


def test_ticket_check_without_inbox_record(
    configured: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["start", "--id", "Z-1", "--type", "task", "--title", "t"]) == 0
    capsys.readouterr()
    assert cli.main(["ticket-check"]) == 0
    assert capsys.readouterr().out.strip() == "Ticket unchanged."


# --- PUT endpoint -----------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Registry(tmp_path / "home" / "manager.json")))


def test_put_endpoint(client: TestClient, configured: Path) -> None:
    repo = configured
    rid = client.post("/api/repos", json={"path": str(repo)}, headers=H).json()["id"]
    url = f"/api/repos/{rid}/inbox"
    client.post(url, json={"tickets": [ticket()]}, headers=H)
    assert client.put(f"{url}/T-001", json={"title": "x"}).status_code == 403  # no header
    res = client.put(f"{url}/T-001", json={"title": "New", "type": "bug"}, headers=H).json()
    assert res["running"] is False and res["ticket"]["revision"] == 2
    assert res["ticket"]["type"] == "bug" and "jira" not in res
    assert cli.main(["start", "--id", "T-001", "--type", "task", "--title", "New"]) == 0
    res = client.put(f"{url}/T-001", json={"description": "more"}, headers=H).json()
    assert res["running"] is True
    bad = client.put(f"{url}/T-001", json={"id": "T-777"}, headers=H)
    assert bad.status_code == 400 and "locked" in bad.json()["detail"]
    assert client.put(f"{url}/T-404", json={"title": "x"}, headers=H).status_code == 404


# --- Jira sync --------------------------------------------------------------------------------


@pytest.fixture
def fake() -> Iterator[FakeJira]:
    f = FakeJira()
    yield f
    f.stop()


@pytest.fixture
def jira_repo(repo: Path, fake: FakeJira, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CCORCH_MANAGER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.delenv("CCORCH_JIRA_TOKEN", raising=False)
    cfg = config.deep_merge(
        config.DEFAULTS, {"jira": {"enabled": True, "url": fake.url, "project_key": "PROJ"}}
    )
    config.write(repo, cfg)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "cfg")
    git(repo, "push")
    jira.save_creds(fake.url, "me@example.com", "tok")
    monkeypatch.chdir(repo)
    return repo


def test_edit_is_sent_to_jira_and_jira_edits_are_picked_up(
    client: TestClient, jira_repo: Path, fake: FakeJira, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add_issue("PROJ-5", "Fix login", type_="Bug")
    assert cli.main(["inbox", "show", "PROJ-5"]) == 0
    rid = client.post("/api/repos", json={"path": str(jira_repo)}, headers=H).json()["id"]
    res = client.put(
        f"/api/repos/{rid}/inbox/PROJ-5", json={"title": "Fix the login page"}, headers=H
    ).json()
    assert res["jira"] == "updated"
    assert fake.issues["PROJ-5"]["fields"]["summary"] == "Fix the login page"
    assert "works" in fake.issues["PROJ-5"]["fields"]["description"]
    bad = client.put(f"/api/repos/{rid}/inbox/PROJ-5", json={"id": "PROJ-6"}, headers=H)
    assert bad.status_code == 400

    assert cli.main(["start", "--id", "PROJ-5", "--type", "bug", "--title", "Fix login"]) == 0
    capsys.readouterr()
    # Our own save is not read back as a Jira change... but the revision is new for the session
    # that started after it, so it starts up to date.
    assert cli.main(["ticket-check"]) == 0
    assert capsys.readouterr().out.strip() == "Ticket unchanged."

    fields = fake.issues["PROJ-5"]["fields"]
    fields["summary"] = "Edited in Jira"
    fields["updated"] = "2026-12-01T00:00:00.000+0000"
    assert cli.main(["ticket-check"]) == 0
    out = capsys.readouterr().out
    assert "TICKET UPDATED" in out and "Changed: title" in out and "Edited in Jira" in out


def test_jira_down_on_save_and_check_is_only_a_warning(
    client: TestClient, jira_repo: Path, fake: FakeJira, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add_issue("PROJ-5")
    assert cli.main(["inbox", "show", "PROJ-5"]) == 0
    rid = client.post("/api/repos", json={"path": str(jira_repo)}, headers=H).json()["id"]
    assert cli.main(["start", "--id", "PROJ-5", "--type", "bug", "--title", "x"]) == 0
    fake.stop()
    res = client.put(f"/api/repos/{rid}/inbox/PROJ-5", json={"title": "New"}, headers=H)
    assert res.status_code == 200 and "Jira was not updated" in res.json()["jira"]
    capsys.readouterr()
    assert cli.main(["ticket-check"]) == 0
    out = capsys.readouterr().out
    assert "Jira warning" in out and "TICKET UPDATED" in out
