"""Active-ticket state, kept in `.git/ccorch/` so it is never committed or seen by git status."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class TicketState:
    ticket_id: str
    type: str
    title: str
    branch: str
    base: str
    started_at: str = field(default_factory=now)
    active: bool = True
    hold: bool = False  # Stop hook does nothing while true (e.g. waiting for the user)
    phases_done: int = 0
    fix_iterations: int = 0
    gate_failures: int = 0  # consecutive Stop-hook blocks; reset on a passing gate
    last_gate_pass: str | None = None  # tree fingerprint of the last passing gate
    commits: list[str] = field(default_factory=list)
    mr_url: str | None = None
    notes: list[str] = field(default_factory=list)  # handoff notes between phases


class StateStore:
    def __init__(self, git_dir: Path) -> None:
        self.dir = git_dir / "ccorch"
        self.path = self.dir / "state.json"
        self.history = self.dir / "history.jsonl"

    def load(self) -> TicketState | None:
        if not self.path.is_file():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        known = TicketState.__dataclass_fields__
        return TicketState(**{k: v for k, v in data.items() if k in known})

    def save(self, state: TicketState) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def active(self) -> TicketState | None:
        state = self.load()
        return state if state and state.active else None

    def finish(self, state: TicketState, outcome: str) -> None:
        state.active = False
        self.save(state)
        self.dir.mkdir(parents=True, exist_ok=True)
        record = {**asdict(state), "finished_at": now(), "outcome": outcome}
        with self.history.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def read_history(self, limit: int = 50) -> list[dict[str, object]]:
        if not self.history.is_file():
            return []
        lines = self.history.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in reversed(lines) if line.strip()]
