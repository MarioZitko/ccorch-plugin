from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccorch_lib import cli, config, jira, ticket_ids
from ccorch_lib.git import Git
from ccorch_lib.inbox import Inbox
from ccorch_lib.state import StateStore
from server import Registry, create_app
from tests.conftest import git
from tests.fake_jira import FakeJira

H = {"X-CCorch": "1"}


def cfg_for(prefix: str = "PROJ", source: str = "git", **jira_over: object) -> dict[str, object]:
    over: dict[str, object] = {"intake": {"id_prefix": prefix, "id_source": source}}
    if jira_over:
        over["jira"] = jira_over
    return config.deep_merge(config.DEFAULTS, over)


def commit(repo: Path, message: str) -> None:
    git(repo, "commit", "--allow-empty", "-m", message)


@pytest.fixture
def team_repo(repo: Path) -> Path:
    """Remote has a branch PROJ-7, a commit [PROJ-12] and a merge of a deleted PROJ-15 branch."""
    git(repo, "switch", "-c", "feature/PROJ-7-x")
    git(repo, "push", "-u", "origin", "feature/PROJ-7-x")
    git(repo, "switch", "main")
    commit(repo, "[PROJ-12] y")
    commit(repo, "Merge branch 'fix/PROJ-15-z' into 'main'")
    git(repo, "push", "origin", "main")
    return repo


def store(repo: Path) -> StateStore:
    return StateStore(Git(repo).git_dir())


def test_git_source_counts_branches_and_merged_history(team_repo: Path) -> None:
    Inbox(store(team_repo)).add([{"id": "PROJ-3", "type": "bug", "title": "local"}])
    got = ticket_ids.next_ids(cfg_for(), team_repo, store(team_repo), 2)
    assert got.ids == ["PROJ-16", "PROJ-17"]
    assert got.source == "git" and got.warning is None
    assert got.last == "PROJ-15 (origin)"


def test_width_is_copied_from_remote_but_local_is_padded(repo: Path) -> None:
    commit(repo, "[PROJ-1412] big")
    git(repo, "push", "origin", "main")
    assert ticket_ids.next_ids(cfg_for(), repo, store(repo), 1).ids == ["PROJ-1413"]
    assert ticket_ids.next_ids(cfg_for(source="local"), repo, store(repo), 1).ids == ["PROJ-001"]


def test_local_ids_are_never_reused(team_repo: Path) -> None:
    Inbox(store(team_repo)).add([{"id": "PROJ-020", "type": "bug", "title": "local"}])
    assert ticket_ids.next_ids(cfg_for(), team_repo, store(team_repo), 1).ids == ["PROJ-021"]


def test_no_remote_falls_back_with_warning(tmp_path: Path) -> None:
    work = tmp_path / "solo"
    work.mkdir()
    git(work, "init", "-b", "main")
    got = ticket_ids.next_ids(cfg_for(), work, store(work), 1)
    assert got.ids == ["PROJ-001"] and got.source == "local"
    assert got.warning and "numbered from this clone only" in got.warning


def test_unreachable_remote_falls_back_with_warning(repo: Path, tmp_path: Path) -> None:
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    got = ticket_ids.next_ids(cfg_for(), repo, store(repo), 1)
    assert got.ids == ["PROJ-001"] and got.warning and "Couldn't read origin" in got.warning


def test_prefix_matching_is_strict(repo: Path) -> None:
    commit(repo, "XPROJ-99 and PROJ-12a and PROJ-8x but PROJ-5, (PROJ-6)")
    git(repo, "push", "origin", "main")
    assert ticket_ids.next_ids(cfg_for(), repo, store(repo), 1).ids == ["PROJ-7"]


def test_cli_next_id_and_inbox_add(
    team_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config.write(team_repo, cfg_for())
    monkeypatch.chdir(team_repo)
    assert cli.main(["next-id", "--count", "2"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "PROJ-16",
        "PROJ-17",
        "# source: git (highest PROJ-15 (origin))",
    ]
    args = ["inbox", "add", "--type", "bug", "--title", "Fix footer", "--criteria", "a"]
    assert cli.main([*args, "--criteria", "b", "--size", "small"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "PROJ-16"
    item = Inbox(store(team_repo)).get("PROJ-16")
    assert item and item["acceptance_criteria"] == ["a", "b"] and item["size"] == "small"
    assert cli.main(["inbox", "add", "--title", "Own id", "--id", "ABC-1"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "ABC-1"
    assert cli.main(["inbox", "add", "--type", "bug"]) == 2


# --- Jira source ---------------------------------------------------------------------------


@pytest.fixture
def fake() -> Iterator[FakeJira]:
    f = FakeJira()
    yield f
    f.stop()


@pytest.fixture
def jira_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeJira) -> None:
    monkeypatch.setenv("CCORCH_MANAGER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.delenv("CCORCH_JIRA_TOKEN", raising=False)
    jira.save_creds(fake.url, "me@example.com", "tok")


def test_jira_source(repo: Path, fake: FakeJira, jira_env: None) -> None:
    fake.add_issue("PROJ-41")
    cfg = cfg_for(source="jira", enabled=True, url=fake.url, project_key="PROJ")
    got = ticket_ids.next_ids(cfg, repo, store(repo), 1)
    assert got.ids == ["PROJ-42"] and got.source == "jira" and got.last == "PROJ-41 (Jira)"


def test_jira_down_falls_back(repo: Path, jira_env: None) -> None:
    cfg = cfg_for(source="jira", enabled=True, url="http://127.0.0.1:9", project_key="PROJ")
    jira.save_creds("http://127.0.0.1:9", "me@example.com", "tok")
    got = ticket_ids.next_ids(cfg, repo, store(repo), 1)
    assert got.ids == ["PROJ-001"] and got.warning and "Jira" in got.warning


def test_inbox_add_creates_jira_issue(
    repo: Path,
    fake: FakeJira,
    jira_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = cfg_for(source="jira", enabled=True, url=fake.url, project_key="PROJ", create_issues=True)
    config.write(repo, cfg)
    monkeypatch.chdir(repo)
    assert cli.main(["inbox", "add", "--type", "bug", "--title", "Via CLI"]) == 0
    out = capsys.readouterr().out
    print(out)
    assert out.splitlines()[0] == "PROJ-101"
    item = Inbox(store(repo)).get("PROJ-101")
    assert item and item["jira_key"] == "PROJ-101"
    fake.stop()
    assert cli.main(["inbox", "add", "--title", "Jira gone"]) == 0
    out = capsys.readouterr().out
    assert "Jira warning" in out


# --- validation and server -----------------------------------------------------------------


def test_validation() -> None:
    config.validate(cfg_for(source="git"))
    with pytest.raises(config.ConfigError, match="id_source must be one of"):
        config.validate(cfg_for(source="svn"))
    with pytest.raises(config.ConfigError, match="needs \\[jira\\] enabled"):
        config.validate(cfg_for(source="jira"))
    jira_on = {"enabled": True, "url": "https://x.atlassian.net", "project_key": "PROJ"}
    config.validate(cfg_for("PROJ", "jira", **jira_on))
    with pytest.raises(config.ConfigError, match="id_prefix = jira.project_key"):
        config.validate(cfg_for("T", "jira", **jira_on))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Registry(tmp_path / "home" / "manager.json")))


def test_next_id_endpoint(client: TestClient, team_repo: Path) -> None:
    config.write(team_repo, cfg_for())
    client.post("/api/repos", json={"path": str(team_repo)}, headers=H)
    res = client.get("/api/repos/0/next-id", params={"count": 2}).json()
    assert res == {
        "ids": ["PROJ-16", "PROJ-17"],
        "source": "git",
        "last": "PROJ-15 (origin)",
        "warning": None,
    }


def test_intake_returns_id_warning(
    client: TestClient, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ccorch_lib import intake

    config.write(repo, cfg_for())
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    client.post("/api/repos", json={"path": str(repo)}, headers=H)

    class Answer:
        cost_usd = 0.0
        duration_ms = 1
        model = "fake"

    monkeypatch.setattr(
        intake,
        "extract",
        lambda *a, **k: ([{"type": "bug", "title": "t"}], [], Answer()),
    )
    res = client.post("/api/repos/0/intake", headers=H, json={"text": "x"}).json()
    assert res["tickets"][0]["id"] == "PROJ-001"
    assert res["id_source"] == "local" and "Couldn't read origin" in res["id_warning"]
