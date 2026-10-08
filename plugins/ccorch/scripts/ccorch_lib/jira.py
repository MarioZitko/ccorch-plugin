"""Minimal Jira client (stdlib only) + personal credential storage.

API versions used (checked against Atlassian's docs 2026-10; see docs/plans/2-jira.md):
- Everything except search uses REST v2 (`/rest/api/2/...`), which exists on Cloud and on
  Server/Data Center and takes a plain-text (wiki markup) `description` / comment `body`.
- Search: Cloud uses `GET /rest/api/3/search/jql` (the old `/search` endpoints were removed in
  2025); Server/DC uses `GET /rest/api/2/search`. Only `key` is read, so ADF does not matter.
- Auth: Cloud = Basic `email:api_token`; Server/DC = `Bearer <personal access token>`.

Credentials are personal: env vars `CCORCH_JIRA_TOKEN` (+ `CCORCH_JIRA_EMAIL`) or
`<ccorch home>/credentials.json`. They never go in the repo and never appear in errors.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ccorch_lib.home import ccorch_home

CRITERIA_HEADING = "h3. Acceptance criteria"


class JiraError(RuntimeError):
    """A short, token-free reason a Jira call failed."""


# --- credentials ---------------------------------------------------------------------------


@dataclass
class Creds:
    email: str
    token: str


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


def credentials_path() -> Path:
    return ccorch_home() / "credentials.json"


def _read_file() -> dict[str, Any]:
    path = credentials_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stored(url: str) -> dict[str, str]:
    entry = _read_file().get("jira", {})
    found = entry.get(normalize_url(url)) if isinstance(entry, dict) else None
    return found if isinstance(found, dict) else {}


def load_creds(url: str) -> Creds | None:
    env_token = os.environ.get("CCORCH_JIRA_TOKEN", "").strip()
    if env_token:
        return Creds(os.environ.get("CCORCH_JIRA_EMAIL", "").strip(), env_token)
    stored = _stored(url)
    token = str(stored.get("token", ""))
    return Creds(str(stored.get("email", "")), token) if token else None


def save_creds(url: str, email: str, token: str) -> None:
    """Store the login for `url`. An empty token keeps the stored one."""
    key = normalize_url(url)
    if not key:
        raise JiraError("Jira URL is required to save a login")
    data = _read_file()
    jira = data.setdefault("jira", {})
    old = jira.get(key, {}) if isinstance(jira.get(key), dict) else {}
    jira[key] = {"email": email.strip(), "token": token.strip() or str(old.get("token", ""))}
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if sys.platform != "win32":
        tmp.chmod(0o600)
    tmp.replace(path)


def creds_status(url: str) -> dict[str, Any]:
    """What the settings page may know: never the token itself."""
    env = bool(os.environ.get("CCORCH_JIRA_TOKEN", "").strip())
    creds = load_creds(url)
    return {
        "has_token": creds is not None,
        "email": creds.email if creds else "",
        "from_env": env,
    }


# --- client --------------------------------------------------------------------------------


@dataclass
class Issue:
    key: str
    url: str
    summary: str
    description: str
    type: str
    status: str
    updated: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # never forward the Authorization header to another host


class Jira:
    def __init__(self, url: str, deployment: str, creds: Creds, timeout_s: float = 15) -> None:
        self.base = url.strip().rstrip("/")
        self.deployment = deployment
        self.creds = creds
        self.timeout_s = timeout_s
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _auth(self) -> str:
        if self.deployment == "server":
            return f"Bearer {self.creds.token}"
        if not self.creds.email:
            raise JiraError("Jira Cloud needs the email of your Atlassian account")
        raw = f"{self.creds.email}:{self.creds.token}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json", "Authorization": self._auth()}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise JiraError(_http_message(exc)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise JiraError(f"cannot reach {self.base}: {reason}") from None
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise JiraError(f"{self.base} did not answer with JSON (wrong URL?)") from None

    # v2 on Cloud and Server/DC
    def myself(self) -> dict[str, Any]:
        out: dict[str, Any] = self._call("GET", "/rest/api/2/myself")
        return out

    # v2
    def project(self, key: str) -> dict[str, Any]:
        data = self._call("GET", f"/rest/api/2/project/{urllib.parse.quote(key)}")
        return {
            "name": str(data.get("name", key)),
            "issue_types": [str(t["name"]) for t in data.get("issueTypes", [])],
        }

    # v2
    def statuses(self, key: str) -> list[str]:
        data = self._call("GET", f"/rest/api/2/project/{urllib.parse.quote(key)}/statuses")
        names: list[str] = []
        for issue_type in data:
            for st in issue_type.get("statuses", []):
                if st["name"] not in names:
                    names.append(st["name"])
        return names

    # v2
    def get_issue(self, key: str) -> Issue:
        data = self._call(
            "GET",
            f"/rest/api/2/issue/{urllib.parse.quote(key)}",
            query={"fields": "summary,description,issuetype,status,updated"},
        )
        f = data.get("fields", {})
        return Issue(
            key=str(data.get("key", key)),
            url=f"{self.base}/browse/{data.get('key', key)}",
            summary=str(f.get("summary") or ""),
            description=str(f.get("description") or ""),
            type=str((f.get("issuetype") or {}).get("name", "")),
            status=str((f.get("status") or {}).get("name", "")),
            updated=str(f.get("updated") or ""),
        )

    # v2
    def create_issue(self, project: str, type_name: str, summary: str, description: str) -> str:
        data = self._call(
            "POST",
            "/rest/api/2/issue",
            {
                "fields": {
                    "project": {"key": project},
                    "issuetype": {"name": type_name},
                    "summary": summary,
                    "description": description,
                }
            },
        )
        return str(data["key"])

    # v2
    def update_issue(self, key: str, summary: str, description: str) -> None:
        self._call(
            "PUT",
            f"/rest/api/2/issue/{urllib.parse.quote(key)}",
            {"fields": {"summary": summary, "description": description}},
        )

    # v2
    def transitions(self, key: str) -> list[dict[str, str]]:
        data = self._call("GET", f"/rest/api/2/issue/{urllib.parse.quote(key)}/transitions")
        return [
            {
                "id": str(t["id"]),
                "name": str(t.get("name", "")),
                "to": str((t.get("to") or {}).get("name", "")),
            }
            for t in data.get("transitions", [])
        ]

    def move(self, key: str, status: str) -> str:
        """'moved' | 'already' | 'no_transition'. Matches the status name, then the transition."""
        want = status.strip().lower()
        if self.get_issue(key).status.lower() == want:
            return "already"
        options = self.transitions(key)
        chosen = next((t for t in options if t["to"].lower() == want), None) or next(
            (t for t in options if t["name"].lower() == want), None
        )
        if chosen is None:
            return "no_transition"
        # v2
        self._call(
            "POST",
            f"/rest/api/2/issue/{urllib.parse.quote(key)}/transitions",
            {"transition": {"id": chosen["id"]}},
        )
        return "moved"

    # v2
    def comment(self, key: str, text: str) -> None:
        self._call("POST", f"/rest/api/2/issue/{urllib.parse.quote(key)}/comment", {"body": text})

    def search_last_key(self, project: str) -> str | None:
        """Highest key in `project` (plan 3 uses it to pick the next ticket number)."""
        # By key, not created date: an issue moved in from another project gets a new, higher
        # key but keeps its old created date.
        query = {"jql": f"project = {project} ORDER BY key DESC", "maxResults": "1"}
        if self.deployment == "server":
            path = "/rest/api/2/search"  # v2 (Server/DC)
            query["fields"] = "key"
        else:
            path = "/rest/api/3/search/jql"  # v3 (Cloud; old /search was removed)
            query["fields"] = "key"
        data = self._call("GET", path, query=query)
        issues = data.get("issues", []) if isinstance(data, dict) else []
        return str(issues[0]["key"]) if issues else None


def _http_message(exc: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        body = json.loads(exc.read())
        parts = [str(m) for m in body.get("errorMessages", [])]
        parts += [f"{k}: {v}" for k, v in (body.get("errors") or {}).items()]
        detail = "; ".join(parts)
    except (ValueError, AttributeError, OSError):
        pass
    hints = {401: " (wrong email or API token?)", 403: " (not allowed)", 404: " (not found)"}
    return f"HTTP {exc.code}{hints.get(exc.code, '')}" + (f": {detail}" if detail else "")


def client_for(cfg: dict[str, Any]) -> Jira | None:
    """A client for the repo's Jira settings, or None if Jira is off or has no login."""
    jc = cfg["jira"]
    if not jc["enabled"]:
        return None
    creds = load_creds(jc["url"])
    if creds is None:
        return None
    return Jira(jc["url"], jc["deployment"], creds)


def is_jira_key(cfg: dict[str, Any], ticket_id: str) -> bool:
    jc = cfg["jira"]
    return bool(jc["enabled"]) and bool(
        re.fullmatch(rf"{re.escape(jc['project_key'])}-\d+", ticket_id.strip())
    )


# --- text <-> ticket -----------------------------------------------------------------------


def ticket_description(t: dict[str, Any]) -> str:
    text = str(t.get("description", "")).strip()
    criteria = t.get("acceptance_criteria") or []
    if criteria:
        text += f"\n\n{CRITERIA_HEADING}\n" + "\n".join(f"* {c}" for c in criteria)
    return text.strip()


def parse_issue(cfg: dict[str, Any], issue: Issue) -> dict[str, Any]:
    """Inbox ticket dict for a Jira issue (unknown issue types become `task`)."""
    head, _, tail = issue.description.partition(CRITERIA_HEADING)
    # Wiki-markup list items: "* a", "# a", "- a".
    criteria = [c for ln in tail.splitlines() if (c := ln.strip().lstrip("*#-• \t").strip())]
    by_name = {v.lower(): k for k, v in cfg["jira"]["issue_types"].items()}
    return {
        "id": issue.key,
        "type": by_name.get(issue.type.lower(), "task"),
        "title": issue.summary,
        "description": head.strip(),
        "acceptance_criteria": criteria,
        "jira_key": issue.key,
        "jira_url": issue.url,
        "jira_status": issue.status,
        "jira_updated": issue.updated,
    }
