"""Query the wiki: retrieve relevant pages, synthesize an answer with
citations, and optionally file the answer back as a new wiki query page.

The "file good answers back into the wiki" idea is core to the methodology —
explorations should compound just like ingested sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import blocks, prompts
from .embedding import Embedder
from .llm import LLMClient
from .search import SearchHit, search
from .store import WikiProject, today_str

MAX_CONTEXT_CHARS = 24_000


@dataclass
class QueryResult:
    answer: str
    hits: List[SearchHit] = field(default_factory=list)
    saved_path: Optional[str] = None


def _build_context(hits: List[SearchHit]) -> str:
    parts: List[str] = []
    budget = MAX_CONTEXT_CHARS
    for h in hits:
        block = f"### [[{h.page.slug}]] — {h.page.title}\n{h.page.body.strip()}\n"
        if len(block) > budget:
            block = block[:budget]
        parts.append(block)
        budget -= len(block)
        if budget <= 0:
            break
    return "\n".join(parts)


def query(
    project: WikiProject,
    client: LLMClient,
    question: str,
    *,
    embedder: Optional[Embedder] = None,
    k: int = 8,
    save: bool = False,
) -> QueryResult:
    hits = search(project, question, embedder=embedder, k=k)
    if not hits:
        return QueryResult(answer="The wiki has no pages yet. Ingest some sources first.")

    context = _build_context(hits)
    system = prompts.build_query_prompt(project.read_purpose(), context)
    answer = client.chat(system, question, temperature=0.3)

    saved_path: Optional[str] = None
    if save:
        today = today_str()
        save_system = prompts.build_query_save_prompt(question, answer, today)
        gen = client.chat(save_system, "Generate the query page now.", temperature=0.2)
        for fb in blocks.parse_files(gen):
            rel = project.write_block(fb.path, fb.content)
            if rel:
                saved_path = rel
                project.append_log(f"## [{today}] query | {question[:60]}")
                break

    return QueryResult(answer=answer, hits=hits, saved_path=saved_path)
