"""GitLab merge request via push options (no API token needed).

https://docs.gitlab.com/topics/git/commit/#push-options-for-merge-requests
Git refuses push options containing newlines, so title/description are flattened to one line.
"""

from __future__ import annotations

import re
from typing import Any

from ccorch_lib.config import mr_target

DESCRIPTION_MAX = 1000


def one_line(text: str) -> str:
    return re.sub(r"\s*[\r\n]+\s*", " · ", text.strip())


def render_title(cfg: dict[str, Any], *, ticket_id: str, title: str, type: str, branch: str) -> str:
    return one_line(
        cfg["mr"]["title"].format(ticket_id=ticket_id, title=title, type=type, branch=branch)
    )


def push_options(cfg: dict[str, Any], *, title: str, description: str) -> list[str]:
    mr = cfg["mr"]
    opts = [
        "merge_request.create",
        f"merge_request.target={mr_target(cfg)}",
        f"merge_request.title={one_line(title)}",
    ]
    desc = one_line(description)[:DESCRIPTION_MAX]
    if desc:
        opts.append(f"merge_request.description={desc}")
    if mr["remove_source_branch"]:
        opts.append("merge_request.remove_source_branch")
    if mr["squash"]:
        opts.append("merge_request.squash")
    if mr["draft"]:
        opts.append("merge_request.draft")
    if mr["auto_merge"]:
        # Older name, still accepted by newer GitLab; `auto_merge` only exists on 17.x+.
        opts.append("merge_request.merge_when_pipeline_succeeds")
    for label in mr["labels"]:
        if label.strip():
            opts.append(f"merge_request.label={label.strip()}")
    if mr["assignee"].strip():
        opts.append(f"merge_request.assign={mr['assignee'].strip()}")
    return opts
