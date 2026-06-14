"""Build a knowledge graph from wiki pages and their ``[[wikilink]]`` references.

Nodes are wiki pages (colored by frontmatter ``type``); edges are wikilinks
found in page bodies. Used by both the CLI and the GUI's graph view. Mirrors
the relationship extraction in ``src/lib/wiki-graph.ts``.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .store import WikiProject

WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")

# Node colors by page type (consumed by the GUI; harmless for the CLI).
TYPE_COLORS: Dict[str, str] = {
    "entity": "#4f9da6",
    "concept": "#c97b5a",
    "source": "#6c7a89",
    "query": "#b56576",
    "comparison": "#8e7cc3",
    "synthesis": "#5a8f69",
    "overview": "#2f3640",
}
DEFAULT_COLOR = "#8395a7"


def _slug_of(rel_path: str) -> str:
    return rel_path.rsplit("/", 1)[-1][:-3] if rel_path.endswith(".md") else rel_path


def extract_links(body: str) -> List[str]:
    """Return the list of target slugs referenced via [[wikilink]] in a body."""
    links = []
    for m in WIKILINK_RE.finditer(body):
        target = m.group(1).strip()
        # Strip a leading path / trailing .md if the model wrote one.
        target = target.rsplit("/", 1)[-1]
        if target.endswith(".md"):
            target = target[:-3]
        if target:
            links.append(target)
    return links


def build_graph(project: WikiProject) -> Dict[str, list]:
    """Return {nodes: [...], edges: [...]} for visualization / API."""
    pages = project.iter_pages()
    slug_to_page = {p.slug: p for p in pages}

    nodes = []
    for p in pages:
        ptype = p.type
        nodes.append({
            "id": p.slug,
            "label": p.title,
            "type": ptype,
            "path": p.path,
            "color": TYPE_COLORS.get(ptype, DEFAULT_COLOR),
        })

    edges = []
    seen = set()
    for p in pages:
        for target in extract_links(p.body):
            if target == p.slug:
                continue
            # Only draw edges to pages that actually exist.
            if target not in slug_to_page:
                continue
            key = (p.slug, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"from": p.slug, "to": target})

    # Mark orphans (no inbound or outbound edges) for the lint/insights view.
    linked = set()
    for e in edges:
        linked.add(e["from"])
        linked.add(e["to"])
    for n in nodes:
        n["orphan"] = n["id"] not in linked

    return {"nodes": nodes, "edges": edges}


def find_orphans(project: WikiProject) -> List[str]:
    g = build_graph(project)
    return [n["id"] for n in g["nodes"] if n.get("orphan")]
