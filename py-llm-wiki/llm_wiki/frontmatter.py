"""Parse and serialize YAML frontmatter on markdown pages.

Every wiki page begins with a strict frontmatter block:

    ---
    type: entity
    title: Example
    created: 2026-05-31
    ...
    ---
    body...

Mirrors the conventions in the TypeScript implementation's
``src/lib/frontmatter.ts`` (lenient parse, strict re-serialization).
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

import yaml

# Required frontmatter fields and their defaults, in canonical output order.
REQUIRED_ORDER = ["type", "title", "created", "updated", "tags", "related", "sources"]


def parse(text: str) -> Tuple[Dict[str, Any], str]:
    """Split a markdown string into (frontmatter_dict, body).

    Tolerant: if there is no leading ``---`` block, returns ({}, text).
    A leading ```` ```yaml ```` fence (a common LLM mistake) is unwrapped.
    """
    s = text.lstrip("﻿")  # strip BOM if present

    # Unwrap an accidental ```yaml ... ``` fence around the whole thing.
    if s.lstrip().startswith("```"):
        stripped = s.lstrip()
        nl = stripped.find("\n")
        if nl != -1:
            stripped = stripped[nl + 1 :]
            if stripped.rstrip().endswith("```"):
                stripped = stripped.rstrip()[:-3]
        s = stripped

    if not s.startswith("---"):
        return {}, text

    # Find the closing --- delimiter.
    lines = s.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])

    try:
        meta = yaml.safe_load(fm_text) or {}
        if not isinstance(meta, dict):
            meta = {}
    except yaml.YAMLError:
        meta = {}

    return meta, body.lstrip("\n")


def dump(meta: Dict[str, Any], body: str) -> str:
    """Serialize (frontmatter, body) back to a markdown string.

    Required keys are emitted first in canonical order, remaining keys after.
    """
    ordered: Dict[str, Any] = {}
    for key in REQUIRED_ORDER:
        if key in meta:
            ordered[key] = meta[key]
    for key, value in meta.items():
        if key not in ordered:
            ordered[key] = value

    fm = yaml.safe_dump(
        ordered, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).strip()
    body = body.strip("\n")
    return f"---\n{fm}\n---\n\n{body}\n"


def ensure_defaults(meta: Dict[str, Any], *, today: str, page_type: str = "concept") -> Dict[str, Any]:
    """Fill in missing required fields with sensible defaults (non-destructive)."""
    meta = dict(meta)
    meta.setdefault("type", page_type)
    meta.setdefault("title", "")
    meta.setdefault("created", today)
    meta.setdefault("updated", today)
    meta.setdefault("tags", [])
    meta.setdefault("related", [])
    meta.setdefault("sources", [])
    return meta
