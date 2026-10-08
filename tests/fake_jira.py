"""A tiny in-memory Jira (Cloud + Server flavours) on 127.0.0.1 for tests. Records requests."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

STATUSES = ["To Do", "In Progress", "In Review", "Done"]
# status -> {transition name: target status}; deliberately no way from "To Do" to "In Review"
FLOW = {
    "To Do": {"Start progress": "In Progress"},
    "In Progress": {"Send to review": "In Review", "Stop": "To Do"},
    "In Review": {"Finish": "Done", "Back": "In Progress"},
    "Done": {},
}


class FakeJira:
    def __init__(self) -> None:
        self.issues: dict[str, dict[str, Any]] = {}
        self.requests: list[dict[str, Any]] = []
        self.comments: list[tuple[str, str]] = []
        self.counter = 100
        self.fail_create_titles: set[str] = set()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def add_issue(
        self, key: str, summary: str = "Fix it", status: str = "To Do", type_: str = "Bug"
    ) -> None:
        self.issues[key] = {
            "key": key,
            "fields": {
                "summary": summary,
                "description": "Broken.\n\nh3. Acceptance criteria\n* works\n* tested",
                "issuetype": {"name": type_},
                "status": {"name": status},
                "updated": "2026-01-01T00:00:00.000+0000",
            },
        }

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def status_of(self, key: str) -> str:
        return str(self.issues[key]["fields"]["status"]["name"])

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, code: int, body: Any = None) -> None:
                raw = b"" if body is None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                path = self.path.split("?")[0]
                fake.requests.append(
                    {
                        "method": method,
                        "path": self.path,
                        "auth": self.headers.get("Authorization", ""),
                        "body": body,
                    }
                )
                if not self.headers.get("Authorization"):
                    return self._send(401, {"errorMessages": ["not logged in"]})
                self._route(method, path, body)

            def _route(self, method: str, path: str, body: Any) -> None:
                if path == "/rest/api/2/myself":
                    return self._send(200, {"displayName": "Test User"})
                if path == "/rest/api/2/project/PROJ":
                    return self._send(
                        200,
                        {
                            "name": "Project",
                            "issueTypes": [{"name": n} for n in ("Story", "Bug", "Task")],
                        },
                    )
                if path == "/rest/api/2/project/PROJ/statuses":
                    return self._send(
                        200, [{"name": "Bug", "statuses": [{"name": s} for s in STATUSES]}]
                    )
                if path in ("/rest/api/2/search", "/rest/api/3/search/jql"):
                    keys = sorted(fake.issues, key=lambda k: int(k.split("-")[1]))
                    return self._send(200, {"issues": [{"key": keys[-1]}] if keys else []})
                if path == "/rest/api/2/issue" and method == "POST":
                    title = body["fields"]["summary"]
                    if title in fake.fail_create_titles:
                        return self._send(400, {"errors": {"summary": "nope"}})
                    fake.counter += 1
                    key = f"PROJ-{fake.counter}"
                    fake.add_issue(key, title, type_=body["fields"]["issuetype"]["name"])
                    fake.issues[key]["fields"]["description"] = body["fields"]["description"]
                    return self._send(201, {"key": key})
                m = re.fullmatch(r"/rest/api/2/issue/([A-Z]+-\d+)(/transitions|/comment)?", path)
                if not m or m.group(1) not in fake.issues:
                    return self._send(404, {"errorMessages": ["Issue does not exist"]})
                key, sub = m.group(1), m.group(2)
                fields = fake.issues[key]["fields"]
                if sub is None and method == "GET":
                    return self._send(200, fake.issues[key])
                if sub is None and method == "PUT":
                    fields.update(body["fields"])
                    return self._send(204)
                if sub == "/transitions" and method == "GET":
                    flow = FLOW[fake.status_of(key)]
                    return self._send(
                        200,
                        {
                            "transitions": [
                                {"id": name, "name": name, "to": {"name": to}}
                                for name, to in flow.items()
                            ]
                        },
                    )
                if sub == "/transitions" and method == "POST":
                    flow = FLOW[fake.status_of(key)]
                    fields["status"] = {"name": flow[body["transition"]["id"]]}
                    return self._send(204)
                if sub == "/comment" and method == "POST":
                    fake.comments.append((key, body["body"]))
                    return self._send(201, {"id": "1"})
                self._send(404, {"errorMessages": ["unsupported"]})

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

            def do_PUT(self) -> None:
                self._handle("PUT")

        return Handler
