"""Ticket inbox: tickets from transcripts, kept in `.git/ccorch/inbox/` (never committed)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ccorch_lib.branch import clean_ticket_id
from ccorch_lib.config import TICKET_TYPES
from ccorch_lib.state import StateStore, now
from ccorch_lib.ticket_ids import numbers_local

JIRA_FIELDS = ("jira_key", "jira_url", "jira_status", "jira_updated")
FIELDS = ("id", "type", "title", "description", "acceptance_criteria", "size")
EDITABLE = ("type", "size", "title", "description", "acceptance_criteria")
FIELD_LABELS = {"acceptance_criteria": "acceptance criteria"}
HISTORY_KEEP = 10


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

    def _write(self, record: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(record["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        tmp.replace(path)

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
                "revision": 1,
                "created_at": existing["created_at"] if existing else now(),
            }
            self._write(record)
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
        self._write(item)

    def mark_finished(self, tid: str, status: str, mr_url: str | None = None) -> None:
        """Record that the ticket's MR is open (`done`) or it was dropped (`abandoned`)."""
        item = self.get(tid)
        if item is None:
            return
        item.update(status=status, finished_at=now())
        if mr_url:
            item["mr_url"] = mr_url
        self._write(item)

    def update(self, tid: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Edit a ticket at any time. Each real change adds a revision and keeps the old one."""
        existing = self.get(tid)
        if existing is None:
            raise InboxError(f"{tid} is not in the inbox")
        new_id = clean_ticket_id(str(changes.get("id") or existing["id"]))
        if new_id != existing["id"]:
            if existing.get("status", "queued") != "queued":
                raise InboxError(f"{existing['id']} was started; its id is locked to the branch")
            if existing.get("jira_key"):
                raise InboxError(f"{existing['id']} is a Jira issue; its id is the Jira key")
            if self.get(new_id) is not None:
                raise InboxError(f"{new_id} is already in the inbox")
        merged = normalize(
            {**existing, **{k: v for k, v in changes.items() if k in (*EDITABLE, *JIRA_FIELDS)}}
            | {"id": new_id}
        )
        changed = [f for f in EDITABLE if merged[f] != existing.get(f)]
        record = {**existing, **merged}
        revision = int(existing.get("revision", 1))
        if changed:
            snapshot = {
                "revision": revision,
                "updated_at": existing.get("updated_at") or existing.get("created_at", ""),
                **{f: existing.get(f) for f in EDITABLE},
            }
            record["history"] = [*existing.get("history", []), snapshot][-HISTORY_KEEP:]
            record["revision"] = revision + 1
            record["updated_at"] = now()
        elif new_id == existing["id"] and record == existing:
            return existing
        self._write(record)
        if new_id != existing["id"]:
            self._path(existing["id"]).unlink(missing_ok=True)
        return record

    def next_ids(self, prefix: str, count: int) -> list[str]:
        """`count` fresh ids like T-007, not used in the inbox or in past tickets (this clone)."""
        top = numbers_local(self.store, prefix)
        start = top.number if top else 0
        return [f"{prefix}-{start + i:03d}" for i in range(1, count + 1)]


def changed_fields(record: dict[str, Any], seen_revision: int) -> list[str]:
    """Labels of the fields edited since `seen_revision` (all of them if that version is gone)."""
    old = next((h for h in record.get("history", []) if h.get("revision") == seen_revision), None)
    fields = [f for f in EDITABLE if old is None or old.get(f) != record.get(f)]
    return [FIELD_LABELS.get(f, f) for f in fields]
