"""Lint: a periodic health check over the whole wiki.

Builds a compact digest of every page (frontmatter + outbound wikilinks +
orphan flag) and asks the LLM to report contradictions, stale claims, orphan
pages, missing pages, and data gaps. Mirrors ``src/lib/lint.ts``.
"""
from __future__ import annotations

from typing import List

from . import prompts
from .graph import build_graph, extract_links
from .llm import LLMClient
from .store import WikiProject, today_str

MAX_DIGEST_CHARS = 40_000


def _build_digest(project: WikiProject) -> str:
    graph = build_graph(project)
    orphans = {n["id"] for n in graph["nodes"] if n.get("orphan")}

    lines: List[str] = []
    for page in project.iter_pages():
        links = extract_links(page.body)
        flag = " [ORPHAN]" if page.slug in orphans else ""
        snippet = page.body.strip().replace("\n", " ")[:200]
        lines.append(
            f"- {page.slug} (type={page.type}){flag}\n"
            f"  title: {page.title}\n"
            f"  links: {', '.join(links) if links else '(none)'}\n"
            f"  snippet: {snippet}"
        )
    digest = "\n".join(lines)
    return digest[:MAX_DIGEST_CHARS]


def lint(project: WikiProject, client: LLMClient) -> str:
    """Return a markdown health-check report. Also appends a log entry."""
    pages = project.iter_pages()
    if not pages:
        return "The wiki has no pages yet — nothing to lint."

    digest = _build_digest(project)
    system = prompts.build_lint_prompt(project.read_purpose(), project.read_index(), digest)
    report = client.chat(system, "Produce the health-check report now.", temperature=0.3)

    project.append_log(f"## [{today_str()}] lint | {len(pages)} pages reviewed")
    return report
