from __future__ import annotations

import base64
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccorch_lib import cli, config, jira
from ccorch_lib.git import Git
from ccorch_lib.inbox import Inbox
from ccorch_lib.state import StateStore
from server import Registry, create_app
from tests.conftest import git
from tests.fake_jira import FakeJira

H = {"X-CCorch": "1"}
TOKEN = "s3cret-token-value"


@pytest.fixture
def fake() -> Iterator[FakeJira]:
    f = FakeJira()
    yield f
    f.stop()


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "home"
    monkeypatch.setenv("CCORCH_MANAGER_HOME", str(h))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.delenv("CCORCH_JIRA_TOKEN", raising=False)
    monkeypatch.delenv("CCORCH_JIRA_EMAIL", raising=False)
    return h


def jira_cfg(url: str, **over: object) -> dict[str, object]:
    return config.deep_merge(
        config.DEFAULTS,
        {"jira": {"enabled": True, "url": url, "project_key": "PROJ", **over}},
    )


@pytest.fixture
def jira_repo(repo: Path, fake: FakeJira, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = jira_cfg(fake.url, create_issues=True)
    config.write(repo, cfg)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "ccorch config")
    git(repo, "push")
    jira.save_creds(fake.url, "me@example.com", TOKEN)
    monkeypatch.chdir(repo)
    return repo


# --- client / credentials ---------------------------------------------------------------------


def test_auth_header_cloud_and_server(fake: FakeJira) -> None:
    jira.Jira(fake.url, "cloud", jira.Creds("me@example.com", TOKEN)).myself()
    jira.Jira(fake.url, "server", jira.Creds("", TOKEN)).myself()
    cloud, server = (r["auth"] for r in fake.requests)
    assert cloud == "Basic " + base64.b64encode(f"me@example.com:{TOKEN}".encode()).decode()
    assert server == f"Bearer {TOKEN}"


def test_errors_never_contain_the_token(fake: FakeJira) -> None:
    client = jira.Jira(fake.url, "cloud", jira.Creds("me@example.com", TOKEN))
    with pytest.raises(jira.JiraError) as exc:
        client.get_issue("PROJ-999")
    assert "404" in str(exc.value) and TOKEN not in str(exc.value)
    fake.stop()
    with pytest.raises(jira.JiraError) as exc2:
        client.myself()
    assert TOKEN not in str(exc2.value) and "cannot reach" in str(exc2.value)


def test_credentials_env_beats_file_and_mode(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jira.save_creds("https://Acme.atlassian.net/", "a@b.c", "filetoken")
    creds = jira.load_creds("https://acme.atlassian.net")
    assert creds == jira.Creds("a@b.c", "filetoken")
    if sys.platform != "win32":
        mode = stat.S_IMODE((home / "credentials.json").stat().st_mode)
        assert mode == 0o600
    jira.save_creds("https://acme.atlassian.net", "new@b.c", "")  # empty token keeps the old one
    assert jira.load_creds("https://acme.atlassian.net") == jira.Creds("new@b.c", "filetoken")
    monkeypatch.setenv("CCORCH_JIRA_TOKEN", "envtoken")
    monkeypatch.setenv("CCORCH_JIRA_EMAIL", "env@b.c")
    assert jira.load_creds("https://acme.atlassian.net") == jira.Creds("env@b.c", "envtoken")
    assert jira.creds_status("https://acme.atlassian.net")["from_env"] is True


def test_create_get_move(fake: FakeJira) -> None:
    client = jira.Jira(fake.url, "cloud", jira.Creds("me@example.com", TOKEN))
    key = client.create_issue("PROJ", "Bug", "Title", "Body")
    assert key == "PROJ-101"
    assert client.get_issue(key).url == f"{fake.url}/browse/PROJ-101"
    assert client.move(key, "in progress") == "moved"  # case-insensitive status
    assert client.move(key, "In Progress") == "already"
    assert client.move(key, "Done") == "no_transition"  # not reachable from In Progress
    assert client.move(key, "Send to review") == "moved"  # transition name as second choice
    assert fake.status_of(key) == "In Review"
    assert client.search_last_key("PROJ") == key
    server = jira.Jira(fake.url, "server", jira.Creds("", TOKEN))
    assert server.search_last_key("PROJ") == key
    assert any(r["path"].startswith("/rest/api/3/search/jql") for r in fake.requests)
    assert any(r["path"].startswith("/rest/api/2/search") for r in fake.requests)
    searches = [r["path"] for r in fake.requests if "search" in r["path"]]
    assert all("ORDER+BY+key+DESC" in p for p in searches)


def test_ticket_text_round_trip() -> None:
    cfg = jira_cfg("https://x.example.com")
    text = jira.ticket_description({"description": "Why", "acceptance_criteria": ["a", "b"]})
    assert text == "Why\n\nh3. Acceptance criteria\n* a\n* b"
    issue = jira.Issue("PROJ-1", "u", "T", text, "Bug", "To Do", "")
    parsed = jira.parse_issue(cfg, issue)
    assert parsed["type"] == "bug" and parsed["description"] == "Why"
    assert parsed["acceptance_criteria"] == ["a", "b"]
    issue.description = "Why\n\nh3. Acceptance criteria\n# one\n- two\n\n"
    assert jira.parse_issue(cfg, issue)["acceptance_criteria"] == ["one", "two"]


# --- ccorch commands -----------------------------------------------------------------------


def make_commit(repo: Path) -> None:
    (repo / "x.txt").write_text("x\n")
    assert cli.main(["commit", "--no-gate"]) == 0


def test_inbox_show_fetches_and_caches(
    jira_repo: Path, fake: FakeJira, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add_issue("PROJ-5", "Fix login", type_="Bug")
    assert cli.main(["inbox", "show", "PROJ-5"]) == 0
    out = capsys.readouterr().out
    assert "Fix login" in out and f"{fake.url}/browse/PROJ-5" in out and "- works" in out
    item = Inbox(StateStore(Git(jira_repo).git_dir())).get("PROJ-5")
    assert item and item["source"] == "jira" and item["type"] == "bug"
    assert item["jira_status"] == "To Do"
    assert cli.main(["inbox", "show", "PROJ-404"]) == 1
    assert "404" in capsys.readouterr().out


def test_workflow_moves_issue(
    jira_repo: Path, fake: FakeJira, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add_issue("PROJ-5", status="To Do")
    assert cli.main(["start", "--id", "PROJ-5", "--type", "bug", "--title", "Fix login"]) == 0
    assert fake.status_of("PROJ-5") == "In Progress"
    assert "Jira: PROJ-5 -> In Progress" in capsys.readouterr().out
    make_commit(jira_repo)
    assert cli.main(["mr", "--description", "d"]) == 0
    assert fake.status_of("PROJ-5") == "In Review"
    # bare origin is not GitLab, so there is no MR link and so no comment
    assert fake.comments == []


def test_mr_comment_and_abandon(
    jira_repo: Path, fake: FakeJira, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.add_issue("PROJ-6", status="To Do")
    cfg = jira_cfg(fake.url, move_to={"abandoned": "To Do", "start": "In Progress"})
    config.write(jira_repo, cfg)
    git(jira_repo, "commit", "-am", "cfg")
    git(jira_repo, "push")
    assert cli.main(["start", "--id", "PROJ-6", "--type", "task", "--title", "t"]) == 0
    assert cli.main(["finish", "--outcome", "abandoned"]) == 0
    assert fake.status_of("PROJ-6") == "To Do"

    fake.add_issue("PROJ-7", status="To Do")
    assert cli.main(["start", "--id", "PROJ-7", "--type", "task", "--title", "t"]) == 0
    make_commit(jira_repo)
    monkeypatch.setattr(
        "ccorch_lib.git.Git.push_with_options",
        lambda self, branch, options: type(
            "R", (), {"mr_url": "https://gitlab.example.com/mr/1", "output": ""}
        )(),
    )
    assert cli.main(["mr"]) == 0
    assert fake.comments == [("PROJ-7", "Merge request: https://gitlab.example.com/mr/1")]


def test_jira_down_is_only_a_warning(
    jira_repo: Path, fake: FakeJira, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add_issue("PROJ-5")
    fake.stop()
    assert cli.main(["start", "--id", "PROJ-5", "--type", "bug", "--title", "x"]) == 0
    out = capsys.readouterr().out
    assert "Jira warning" in out and TOKEN not in out
    make_commit(jira_repo)
    assert cli.main(["mr"]) == 0
    assert "Jira warning" in capsys.readouterr().out


def test_non_jira_ids_and_missing_login_are_quiet_or_warn(
    jira_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["start", "--id", "T-001", "--type", "bug", "--title", "x"]) == 0
    assert "Jira" not in capsys.readouterr().out
    cli.main(["finish", "--outcome", "abandoned"])
    (jira_repo.parent / "home" / "credentials.json").unlink()
    assert cli.main(["start", "--id", "PROJ-9", "--type", "bug", "--title", "x"]) == 0
    assert "Jira warning: no login" in capsys.readouterr().out


def test_jira_subcommand(
    jira_repo: Path, fake: FakeJira, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add_issue("PROJ-5")
    assert cli.main(["jira", "status", "PROJ-5"]) == 0
    assert "status: To Do" in capsys.readouterr().out
    assert cli.main(["jira", "move", "PROJ-5", "In Progress"]) == 0
    assert fake.status_of("PROJ-5") == "In Progress"
    assert cli.main(["jira", "move", "PROJ-5", "Nowhere"]) == 1
    cli.main(["context"])
    assert "credentials: ok" in capsys.readouterr().out


# --- config ----------------------------------------------------------------------------------


def test_config_validation_and_round_trip(tmp_path: Path) -> None:
    config.validate(config.deep_merge(config.DEFAULTS, {}))  # disabled + empty url is fine
    bad = jira_cfg("ftp://x", project_key="proj", deployment="x")
    with pytest.raises(config.ConfigError) as exc:
        config.validate(bad)  # type: ignore[arg-type]
    for part in ("jira.url", "jira.project_key", "jira.deployment"):
        assert part in str(exc.value)
    with pytest.raises(config.ConfigError):
        config.validate(config.deep_merge(config.DEFAULTS, {"jira": {"create_issues": "yes"}}))
    cfg = jira_cfg(
        "https://x.example.com", issue_types={"bug": "Defect"}, move_to={"abandoned": "Won't do"}
    )
    config.write(tmp_path, cfg)  # type: ignore[arg-type]
    assert config.load(tmp_path)["jira"] == cfg["jira"]  # type: ignore[index]
    assert "[jira.issue_types]" in (tmp_path / config.CONFIG_REL).read_text()


# --- settings page ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Registry(tmp_path / "home" / "manager.json")))


def test_credentials_endpoints_never_return_token(client: TestClient, fake: FakeJira) -> None:
    res = client.put(
        "/api/jira/credentials",
        headers=H,
        json={"url": fake.url, "email": "me@example.com", "token": TOKEN},
    )
    assert res.json() == {"has_token": True, "email": "me@example.com", "from_env": False}
    got = client.get("/api/jira/credentials", params={"url": fake.url})
    assert TOKEN not in got.text and got.json()["has_token"] is True
    assert client.put("/api/jira/credentials", json={"url": fake.url}).status_code == 403


def test_jira_test_reports_problems(client: TestClient, jira_repo: Path, fake: FakeJira) -> None:
    client.post("/api/repos", json={"path": str(jira_repo)}, headers=H)
    cfg = jira_cfg(fake.url, move_to={"start": "In Progress", "mr_opened": "Reviewing"})
    body = client.post("/api/repos/0/jira/test", headers=H, json={"config": cfg}).json()
    assert body["ok"] and body["user"] == "Test User" and "In Review" in body["statuses"]
    assert any("Reviewing" in p for p in body["problems"])
    assert TOKEN not in str(body)
    bad = client.post("/api/repos/0/jira/test", headers=H, json={"config": jira_cfg("nope")}).json()
    assert bad["ok"] is False and bad["problems"]


def test_inbox_create_in_jira_with_partial_failure(
    client: TestClient, jira_repo: Path, fake: FakeJira
) -> None:
    client.post("/api/repos", json={"path": str(jira_repo)}, headers=H)
    fake.fail_create_titles.add("Broken one")
    drafts = [
        {"id": "T-001", "type": "bug", "title": "Good one", "acceptance_criteria": ["ok"]},
        {"id": "T-002", "type": "task", "title": "Broken one"},
    ]
    res = client.post(
        "/api/repos/0/inbox", headers=H, json={"tickets": drafts, "create_in_jira": True}
    ).json()
    assert res["saved"] == ["PROJ-101"]
    assert res["failed"][0]["draft"]["id"] == "T-002" and "summary" in res["failed"][0]["error"]
    item = client.get("/api/repos/0/inbox").json()[0]
    assert item["id"] == "PROJ-101" and item["jira_url"].endswith("/browse/PROJ-101")
    assert fake.issues["PROJ-101"]["fields"]["issuetype"]["name"] == "Bug"
    assert "h3. Acceptance criteria" in fake.issues["PROJ-101"]["fields"]["description"]

    # A draft whose key is a real issue is linked, not created again.
    fake.add_issue("PROJ-9", "Existing")
    res = client.post(
        "/api/repos/0/inbox",
        headers=H,
        json={
            "tickets": [{"id": "PROJ-9", "type": "task", "title": "Existing"}],
            "create_in_jira": True,
        },
    ).json()
    assert res == {"saved": ["PROJ-9"], "failed": []}
    existing = next(t for t in client.get("/api/repos/0/inbox").json() if t["id"] == "PROJ-9")
    assert existing["jira_key"] == "PROJ-9" and existing["jira_url"].endswith("/browse/PROJ-9")
    assert "PROJ-102" not in fake.issues


def test_issue_status_and_manual_move(client: TestClient, jira_repo: Path, fake: FakeJira) -> None:
    client.post("/api/repos", json={"path": str(jira_repo)}, headers=H)
    fake.add_issue("PROJ-5")
    info = client.get("/api/repos/0/jira/issue/PROJ-5").json()
    assert info["status"] == "To Do" and info["targets"] == ["In Progress"]
    ok = client.post(
        "/api/repos/0/jira/issue/PROJ-5/move", headers=H, json={"status": "In Progress"}
    )
    assert ok.json() == {"result": "moved"}
    no = client.post("/api/repos/0/jira/issue/PROJ-5/move", headers=H, json={"status": "Nope"})
    assert no.status_code == 400
