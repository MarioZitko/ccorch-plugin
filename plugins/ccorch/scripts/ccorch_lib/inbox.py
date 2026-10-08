"""Ticket inbox: tickets from transcripts, kept in `.git/ccorch/inbox/` (never committed)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ccorch_lib.branch import clean_ticket_id
from ccorch_lib.config import TICKET_TYPES
from ccorch_lib.state import StateStore, now

JIRA_FIELDS = ("jira_key", "jira_url", "jira_status", "jira_updated")
FIELDS = ("id", "type", "title", "description", "acceptance_criteria", "size")


class InboxError(ValueError):
    pass


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate/clean one ticket dict (from the UI or the model)."""
    tid = clean_ticket_id(str(raw.get("id", "")))
    if not tid:
        raise InboxError("ticket id is required")
    ttype = str(raw.get("type", "task"))
    if ttype not in TICKET_TYPES:
        raise InboxError(f"{tid}: type must be one of {TICKET_TYPES}")
    title = " ".join(str(raw.get("title", "")).split())
    if not title:
        raise InboxError(f"{tid}: title is required")
    criteria = raw.get("acceptance_criteria", [])
    if isinstance(criteria, str):
        criteria = criteria.splitlines()
    size = raw.get("size", "big")
    jira_extra = {k: str(raw[k]) for k in JIRA_FIELDS if raw.get(k)}
    return {
        **jira_extra,
        "id": tid,
        "type": ttype,
        "title": title,
        "description": str(raw.get("description", "")).strip(),
        "acceptance_criteria": [str(c).strip(" -*•\t") for c in criteria if str(c).strip(" -*•\t")],
        "size": size if size in ("small", "big") else "big",
    }


def to_markdown(t: dict[str, Any]) -> str:
    lines = [
        f"Ticket {t['id']} ({t['type']}, looks {t.get('size', 'big')})",
        "",
        f"Title: {t['title']}",
        "",
        "Description:",
        t["description"] or "(none)",
        "",
        "Acceptance criteria:",
    ]
    lines += [f"- {c}" for c in t["acceptance_criteria"]] or ["(none)"]
    return "\n".join(lines)


class Inbox:
    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.dir = store.dir / "inbox"

    def _path(self, tid: str) -> Path:
        return self.dir / f"{clean_ticket_id(tid)}.json"

    def items(self) -> list[dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        items = [json.loads(p.read_text(encoding="utf-8")) for p in self.dir.glob("*.json")]
        return sorted(items, key=lambda t: (t.get("status") != "queued", t.get("created_at", "")))

    @staticmethod
    def normalize_ticket(raw: dict[str, Any]) -> dict[str, Any]:
        return normalize(raw)

    def get(self, tid: str) -> dict[str, Any] | None:
        path = self._path(tid)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def add(self, tickets: list[dict[str, Any]], source: str = "transcript") -> list[str]:
        cleaned = [normalize(t) for t in tickets]
        ids = [t["id"] for t in cleaned]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise InboxError(f"duplicate ticket ids: {sorted(dupes)}")
        for t in cleaned:
            existing = self.get(t["id"])
            if existing and existing.get("status", "queued") != "queued":
                raise InboxError(
                    f"{t['id']} was already started on {existing.get('branch', '?')}; "
                    "edit it instead of saving a new one"
                )
        self.dir.mkdir(parents=True, exist_ok=True)
        for t in cleaned:
            existing = self.get(t["id"])
            record = {
                **t,
                "source": source,
                "status": "queued",
                "created_at": existing["created_at"] if existing else now(),
            }
            self._path(t["id"]).write_text(json.dumps(record, indent=2), encoding="utf-8")
        return ids

    def delete(self, tid: str) -> bool:
        path = self._path(tid)
        if path.is_file():
            path.unlink()
            return True
        return False

    def mark_started(self, tid: str, branch: str) -> None:
        item = self.get(tid)
        if item is None:
            return
        item.update(status="started", branch=branch, started_at=now())
        self._path(tid).write_text(json.dumps(item, indent=2), encoding="utf-8")

    def next_ids(self, prefix: str, count: int) -> list[str]:
        """`count` fresh ids like T-007, not used in the inbox or in past tickets."""
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
        used = [t["id"] for t in self.items()]
        used += [str(h.get("ticket_id", "")) for h in self.store.read_history(10_000)]
        state = self.store.load()
        if state:
            used.append(state.ticket_id)
        top = max((int(m.group(1)) for u in used if (m := pattern.match(u))), default=0)
        return [f"{prefix}-{top + i:03d}" for i in range(1, count + 1)]
