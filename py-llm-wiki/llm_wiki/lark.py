"""Ingest a Lark (Feishu) Wiki space into the local wiki.

This is the second source pathway alongside ``loaders.py``: instead of reading
local files, it pulls documents out of a Lark/Feishu 知识库 and stages them as
markdown, then hands that folder to the normal ``ingest_path`` pipeline. The
knowledge graph is derived from the resulting ``[[wikilinks]]`` automatically
(see ``graph.build_graph``) — there is no separate "build graph" step.

Transport is the already-installed, already-authenticated ``lark-cli`` binary,
invoked as a subprocess. Keeping it out-of-process means this module needs no
Lark SDK or credential handling of its own — the CLI owns auth.

``lark-cli`` surface used (all read-only):
    wiki +node-get  --node-token <url|token>          -> resolve a URL to a node
    wiki +node-list --space-id <id> [--parent-node-token <t>] --page-all
    docs +fetch     --api-version v2 --doc <token> --doc-format markdown

Only ``doc`` / ``docx`` nodes are exported in this MVP. Other node types
(sheet, bitable, mindnote, file, slides) are skipped and counted — register a
handler in ``fetch_markdown`` to extend, the same way ``loaders._READERS`` is
the single extension point for local file types.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

# Node object types that carry textual document content we can export today.
DOC_TYPES = {"doc", "docx"}

# Where exported markdown is staged under the wiki project. A *stable* path (not
# a tempdir) so the sha256 ingest cache makes re-runs incremental.
STAGING_SUBDIR = "raw/lark-export"

# Guard against pathological recursion / cycles in a space.
MAX_NODES = 5000


class LarkError(Exception):
    """A lark-cli call failed (non-zero exit, bad JSON, or error envelope)."""


# ── subprocess plumbing ──────────────────────────────────────────
def lark_cli_available() -> bool:
    return shutil.which("lark-cli") is not None


def _run_lark(args: List[str]) -> dict:
    """Run ``lark-cli <args> --json`` and return the ``data`` payload.

    The CLI envelope is ``{"ok": bool, "data": {...}, ...}``. We raise
    ``LarkError`` (carrying stderr) on a process failure or ``ok != true`` so
    callers get one exception type to handle.
    """
    if not lark_cli_available():
        raise LarkError(
            "lark-cli not found on PATH. Install it and run `lark-cli auth login` "
            "before importing from a Lark wiki."
        )
    cmd = ["lark-cli", *args, "--json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LarkError(f"failed to run {' '.join(cmd)}: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise LarkError(f"lark-cli exited {proc.returncode}: {detail}")

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LarkError(f"could not parse lark-cli JSON output: {exc}") from exc

    # `ok: false` (or a non-zero `code`) signals an API-level error.
    if envelope.get("ok") is False or envelope.get("code") not in (None, 0):
        msg = envelope.get("msg") or envelope.get("error") or json.dumps(envelope)
        raise LarkError(f"lark-cli reported an error: {msg}")

    data = envelope.get("data")
    return data if isinstance(data, dict) else envelope


def _items(data: dict) -> List[dict]:
    """Pull the node array out of a node-list payload (shape-tolerant)."""
    for key in ("items", "nodes", "results"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    return []


# ── data model ───────────────────────────────────────────────────
@dataclass
class LarkNode:
    node_token: str
    obj_token: str
    obj_type: str
    title: str
    has_child: bool
    space_id: str

    @classmethod
    def from_api(cls, d: dict, space_id: str = "") -> "LarkNode":
        return cls(
            node_token=d.get("node_token", ""),
            obj_token=d.get("obj_token", ""),
            obj_type=(d.get("obj_type") or "").lower(),
            title=d.get("title") or "(untitled)",
            has_child=bool(d.get("has_child")),
            space_id=d.get("space_id") or space_id,
        )


@dataclass
class ExportedDoc:
    node: LarkNode
    rel_path: str  # path written, relative to the staging dir


@dataclass
class ExportSummary:
    docs: List[ExportedDoc] = field(default_factory=list)
    skipped: List[LarkNode] = field(default_factory=list)  # unsupported types
    errors: List[str] = field(default_factory=list)         # per-node failures
    staging_dir: Optional[Path] = None


@dataclass
class LarkIngestSummary:
    export: ExportSummary
    results: list = field(default_factory=list)  # List[ingest.IngestResult]


# ── traversal ────────────────────────────────────────────────────
def resolve_root(url_or_token: str) -> LarkNode:
    """Resolve a Lark wiki URL or node/obj token to its node."""
    data = _run_lark(["wiki", "+node-get", "--node-token", url_or_token])
    node = data.get("node") if isinstance(data.get("node"), dict) else data
    return LarkNode.from_api(node)


def walk_space(
    space_id: str,
    parent_node_token: Optional[str] = None,
    *,
    _visited: Optional[set] = None,
) -> Iterator[LarkNode]:
    """Yield every node under a space (or under a parent node), depth-first.

    Descends into any node whose ``has_child`` is set. A visited-set of
    node_tokens guards against cycles and a hard ``MAX_NODES`` cap bounds runaway
    traversal of very large spaces.
    """
    if _visited is None:
        _visited = set()

    args = ["wiki", "+node-list", "--space-id", space_id, "--page-all"]
    if parent_node_token:
        args += ["--parent-node-token", parent_node_token]
    data = _run_lark(args)

    for raw in _items(data):
        node = LarkNode.from_api(raw, space_id=space_id)
        if not node.node_token or node.node_token in _visited:
            continue
        if len(_visited) >= MAX_NODES:
            return
        _visited.add(node.node_token)
        yield node
        if node.has_child:
            yield from walk_space(space_id, node.node_token, _visited=_visited)


def fetch_markdown(node: LarkNode) -> str:
    """Return the markdown body of a document node.

    Only ``doc`` / ``docx`` are supported. To add another type, branch here on
    ``node.obj_type`` (e.g. export a sheet/bitable to markdown) — this is the
    single extension point, mirroring ``loaders._READERS``.
    """
    if node.obj_type not in DOC_TYPES:
        raise LarkError(f"unsupported node type '{node.obj_type}' for {node.title!r}")
    token = node.obj_token or node.node_token
    data = _run_lark(
        ["docs", "+fetch", "--api-version", "v2", "--doc", token, "--doc-format", "markdown"]
    )
    content = data.get("content")
    if not isinstance(content, str):
        # Some payloads nest the rendered body; fall back to common keys.
        content = data.get("markdown") or data.get("text") or ""
    return content


# ── filename helpers ─────────────────────────────────────────────
_SLUG_RE = re.compile(r"[^0-9A-Za-z一-鿿]+")


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip()).strip("-").lower()
    return slug or "untitled"


def _unique_rel_path(slug: str, node: LarkNode, used: set) -> str:
    """A collision-free ``<slug>.md`` name, suffixing the node_token if needed."""
    rel = f"{slug}.md"
    if rel in used:
        suffix = (node.node_token or "x")[-6:]
        rel = f"{slug}-{suffix}.md"
    used.add(rel)
    return rel


def _header(node: LarkNode) -> str:
    """A small provenance header prepended to each exported doc."""
    url = f"https://feishu.cn/wiki/{node.node_token}" if node.node_token else ""
    line = f"<!-- source: lark wiki node {node.node_token} {url} -->".rstrip()
    return f"{line}\n\n# {node.title}\n\n"


# ── export + orchestration ───────────────────────────────────────
def export_wiki(url_or_token: str, dest_dir: Path) -> ExportSummary:
    """Pull every supported document under a Lark wiki into ``dest_dir`` as .md.

    Returns an :class:`ExportSummary` describing what was written, skipped
    (unsupported types), or failed per-node. Raises :class:`LarkError` only for
    fatal problems (CLI missing, root unresolvable).
    """
    root = resolve_root(url_or_token)
    summary = ExportSummary(staging_dir=dest_dir)
    used: set = set()
    dest_dir.mkdir(parents=True, exist_ok=True)

    # The resolved root may itself be a document, a folder ("wiki"/empty type),
    # or have children. Build the full node list accordingly.
    nodes: List[LarkNode] = []
    if root.obj_type in DOC_TYPES:
        nodes.append(root)
    if root.has_child or root.obj_type not in DOC_TYPES:
        # `wiki` container nodes have no obj content; walk their children.
        parent = None if root.obj_type == "wiki" or not root.node_token else root.node_token
        nodes.extend(walk_space(root.space_id, parent))

    for node in nodes:
        if node.obj_type not in DOC_TYPES:
            summary.skipped.append(node)
            continue
        try:
            body = fetch_markdown(node)
        except LarkError as exc:
            summary.errors.append(f"{node.title}: {exc}")
            continue
        rel = _unique_rel_path(_slugify(node.title), node, used)
        (dest_dir / rel).write_text(_header(node) + body, encoding="utf-8")
        summary.docs.append(ExportedDoc(node=node, rel_path=rel))

    return summary


def ingest_lark_wiki(
    project,
    client,
    url_or_token: str,
    *,
    embedder=None,
    progress=None,
    on_result=None,
) -> LarkIngestSummary:
    """Export a Lark wiki into the project's staging dir, then ingest it.

    Shared core for the CLI (`ingest-lark`) and the GUI/API (`/api/ingest-lark`).
    ``project``/``client``/``embedder`` are the same objects the local-file
    ingest path uses; we simply reuse :func:`ingest.ingest_path`.
    """
    from .ingest import ingest_path

    staging = project.root / STAGING_SUBDIR
    export = export_wiki(url_or_token, staging)
    if not export.docs:
        return LarkIngestSummary(export=export, results=[])
    results = ingest_path(project, client, staging, embedder=embedder,
                          progress=progress, on_result=on_result)
    return LarkIngestSummary(export=export, results=results)
