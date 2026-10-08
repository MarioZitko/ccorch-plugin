from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

from ccorch_lib import plugin_update

FAKE = """#!{python}
import json, sys
args = sys.argv[1:]
if args[:2] == ["plugin", "list"]:
    print(json.dumps([{{"id": "ccorch@ccorch-tools", "version": "0.2.0",
                       "installPath": "/x/plugins/cache/ccorch-tools/ccorch/0.2.0"}}]))
elif args[:3] == ["plugin", "marketplace", "list"]:
    print(json.dumps([{{"name": "ccorch-tools", "installLocation": {market!r}}}]))
else:
    sys.exit(1)
"""


def _market(tmp: Path, version: str) -> Path:
    root = tmp / "market"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {"name": "ccorch-tools", "plugins": [{"name": "ccorch", "source": "./plugins/ccorch"}]}
        )
    )
    manifest = root / "plugins" / "ccorch" / ".claude-plugin"
    manifest.mkdir(parents=True)
    (manifest / "plugin.json").write_text(json.dumps({"name": "ccorch", "version": version}))
    return root


def test_version_key_orders_numerically() -> None:
    assert plugin_update.version_key("0.10.0") > plugin_update.version_key("0.9.3")


def test_running_from_cache() -> None:
    assert plugin_update.running_from_cache(Path("/h/.claude/plugins/cache/m/ccorch/0.2.1"))
    assert not plugin_update.running_from_cache(Path("/h/Projects/ccorch-plugin/plugins/ccorch"))


def test_status_reports_available_update(tmp_path: Path) -> None:
    market = _market(tmp_path, "0.3.0")
    exe = tmp_path / "claude"
    exe.write_text(FAKE.format(python=sys.executable, market=str(market)))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    st = plugin_update.status(str(exe), "0.2.0")
    assert st["installed_version"] == "0.2.0" and st["available_version"] == "0.3.0"
    assert st["update_available"] is True and st["marketplace"] == "ccorch-tools"
    assert st["dev_checkout"] is True  # tests run from the repo checkout
