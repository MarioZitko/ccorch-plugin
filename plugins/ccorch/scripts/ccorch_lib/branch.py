"""Branch name rendering. Ported from ccorch `application/branch_naming.py`."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any

_TRANSLITERATION = str.maketrans(
    {
        "č": "c",
        "ć": "c",
        "š": "s",
        "ž": "z",
        "đ": "d",
        "Č": "c",
        "Ć": "c",
        "Š": "s",
        "Ž": "z",
        "Đ": "d",
    }
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_PLACEHOLDERS = frozenset({"type", "ticket_id", "slug"})
_FIELD = re.compile(r"\{([^{}]*)\}")


class BranchNameError(ValueError):
    """The template is malformed or the resulting name is not a valid git ref."""


def slugify(text: str, max_len: int = 40) -> str:
    """Lowercase ASCII slug: Croatian letters transliterated, non-alnum runs become `-`."""
    text = text.translate(_TRANSLITERATION)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = _NON_ALNUM.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def clean_ticket_id(ticket_id: str) -> str:
    # Keep the id recognisable (case preserved) but safe inside a ref name.
    return re.sub(r"[^A-Za-z0-9._-]+", "-", ticket_id.strip()).strip("-.")


def render(
    template: str,
    ticket_type: str,
    ticket_id: str,
    title: str,
    type_prefix: dict[str, str] | None = None,
    slug_max_len: int = 40,
) -> str:
    """Render {type}, {ticket_id}, {slug}; `type_prefix` maps feature/bug/task to {type}."""
    unknown = {name for name in _FIELD.findall(template) if name not in _PLACEHOLDERS}
    if unknown:
        raise BranchNameError(f"unknown placeholder(s) in branch template: {sorted(unknown)}")
    if not clean_ticket_id(ticket_id):
        raise BranchNameError("ticket id is empty")
    values = {
        "type": (type_prefix or {}).get(ticket_type, ticket_type),
        "ticket_id": clean_ticket_id(ticket_id),
        "slug": slugify(title, slug_max_len),
    }
    name = _FIELD.sub(lambda m: values[m.group(1)], template)
    if "{" in name or "}" in name:
        raise BranchNameError(f"malformed branch template: {template!r}")
    name = re.sub(r"/{2,}", "/", name)
    name = re.sub(r"-{2,}", "-", name)
    return name.strip("/").rstrip("-.")


def from_config(cfg: dict[str, Any], ticket_type: str, ticket_id: str, title: str) -> str:
    b = cfg["branch"]
    return render(b["template"], ticket_type, ticket_id, title, b["type_prefix"], b["slug_max_len"])


def validate(name: str, is_valid_ref: Callable[[str], bool]) -> str:
    if not name or name.startswith("-") or not is_valid_ref(name):
        raise BranchNameError(f"invalid git branch name: {name!r}")
    return name
