"""The per-user ccorch directory (`~/.ccorch`): settings-page registry and credentials."""

from __future__ import annotations

import os
from pathlib import Path


def ccorch_home() -> Path:
    """`CCORCH_MANAGER_HOME` if set, else `~/.ccorch`. Shared by the CLI and the settings page."""
    override = os.environ.get("CCORCH_MANAGER_HOME")
    return Path(override) if override else Path.home() / ".ccorch"
