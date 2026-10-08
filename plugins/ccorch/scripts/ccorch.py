# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Entry point for the `ccorch` command (see bin/ccorch) and the plugin hooks."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ccorch_lib.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
