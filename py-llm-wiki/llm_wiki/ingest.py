"""Two-step chain-of-thought ingestion.

For each source: copy it into raw/sources/ (immutable), check the sha256 cache,
then run two sequential LLM calls — analysis, then generation — parse the
FILE/REVIEW blocks, write the pages, append the log, and embed the new/changed
pages into the vector store. Mirrors the pipeline in ``src/lib/ingest.ts``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import blocks, prompts
from .embedding import Embedder
from .llm import LLMClient
from .loaders import discover_sources, read_source
from .store import WikiProject, sha256_text, today_str
from .vectorstore import VectorStore

# Keep prompts within a sane budget; truncate very long sources.
MAX_SOURCE_CHARS = 60_000


@dataclass
class IngestResult:
    source: str
    skipped: bool = False
    files_written: List[str] = field(default_factory=list)
    reviews: int = 0
    error: Optional[str] = None
    elapsed_s: float = 0.0


def _embed_pages(project: WikiProject, embedder: Optional[Embedder], written: List[str]) -> None:
    """Embed the just-written pages into the vector store (best-effort)."""
    if embedder is None:
        return
    store = VectorStore(project.embeddings_path)
    to_embed = []
    for rel in written:
        page = project.read_page(rel)
        if page is None:
            continue
        text = (page.title + "\n\n" + page.body).strip()
        h = sha256_text(text)
        if store.needs_embedding(rel, h):
            to_embed.append((rel, h, text))
    if not to_embed:
        return
    try:
        vectors = embedder.embed([t[2] for t in to_embed])
    except Exception:
        return  # embedding is optional; degrade silently to keyword-only search
    for (rel, h, _), vec in zip(to_embed, vectors):
        store.upsert(rel, h, vec)
    store.save()


def ingest_file(
    project: WikiProject,
    client: LLMClient,
    src: Path,
    *,
    base_dir: Optional[Path] = None,
    cache: Optional[dict] = None,
    embedder: Optional[Embedder] = None,
) -> IngestResult:
    """Ingest a single source file. ``cache`` is mutated in place if provided."""
    rel_name = src.name
    if base_dir is not None:
        try:
            rel_name = str(src.relative_to(base_dir))
        except ValueError:
            rel_name = src.name

    content = read_source(src)
    content_hash = sha256_text(content)

    cache = project.load_ingest_cache() if cache is None else cache
    if cache.get(rel_name) == content_hash:
        return IngestResult(source=rel_name, skipped=True)

    # Copy into the immutable raw collection.
    project.copy_source(src, rel_name)

    truncated = content[:MAX_SOURCE_CHARS]
    today = today_str()
    source_filename = Path(rel_name).name
    source_base = Path(source_filename).stem
    summary_path = f"wiki/sources/{source_base}.md"

    # ── Step 1: analysis ─────────────────────────────────────────
    analysis_system = prompts.build_analysis_prompt(
        project.read_purpose(), project.read_index()
    )
    try:
        analysis = client.chat(analysis_system, truncated, temperature=0.2)
    except Exception as exc:
        return IngestResult(source=rel_name, error=f"analysis failed: {exc}")

    # ── Step 2: generation ───────────────────────────────────────
    generation_system = prompts.build_generation_prompt(
        schema=project.read_schema(),
        purpose=project.read_purpose(),
        index=project.read_index(),
        source_filename=source_filename,
        overview=project.read_overview(),
        today=today,
        source_summary_path=summary_path,
    )
    gen_user = (
        "Here is the analysis of the source. Generate the wiki FILE blocks "
        "(and optional REVIEW blocks) as specified.\n\n"
        f"## Source File\n{source_filename}\n\n"
        f"## Analysis\n{analysis}\n\n"
        f"## Source Content (for reference)\n{truncated}"
    )
    try:
        generation = client.chat(generation_system, gen_user, temperature=0.3)
    except Exception as exc:
        return IngestResult(source=rel_name, error=f"generation failed: {exc}")

    # ── Step 3: write files ──────────────────────────────────────
    file_blocks = blocks.parse_files(generation)
    written: List[str] = []
    for fb in file_blocks:
        if fb.path.endswith("log.md"):
            project.append_log(fb.content)
            continue
        rel = project.write_block(fb.path, fb.content)
        if rel:
            written.append(rel)

    # ── Step 4: reviews ──────────────────────────────────────────
    review_blocks = blocks.parse_reviews(generation)
    if review_blocks:
        lines = [f"\n## [{today}] {source_filename}"]
        for r in review_blocks:
            lines.append(f"- **{r.type}**: {r.title}\n  - {r.description}")
            if r.search:
                lines.append(f"  - SEARCH: {' | '.join(r.search)}")
        project.append_reviews("\n".join(lines))

    # Always ensure a log entry exists for this ingest.
    if not any(fb.path.endswith("log.md") for fb in file_blocks):
        project.append_log(f"## [{today}] ingest | {source_base}")

    # ── Step 5: cache + embeddings ───────────────────────────────
    cache[rel_name] = content_hash
    project.save_ingest_cache(cache)
    _embed_pages(project, embedder, written)

    return IngestResult(source=rel_name, files_written=written, reviews=len(review_blocks))


def reindex_all(project: WikiProject, embedder: Embedder) -> int:
    """Rebuild embeddings for every wiki page. Returns the count embedded."""
    pages = project.iter_pages()
    store = VectorStore(project.embeddings_path)
    valid = {p.path for p in pages}
    store.remove_missing(valid)

    pending = []
    for p in pages:
        text = (p.title + "\n\n" + p.body).strip()
        h = sha256_text(text)
        if store.needs_embedding(p.path, h):
            pending.append((p.path, h, text))
    if pending:
        vectors = embedder.embed([t[2] for t in pending])
        for (rel, h, _), vec in zip(pending, vectors):
            store.upsert(rel, h, vec)
    store.save()
    return len(pages)


def ingest_path(
    project: WikiProject,
    client: LLMClient,
    target: Path,
    *,
    embedder: Optional[Embedder] = None,
    progress=None,
    on_result=None,
    max_new: Optional[int] = None,
) -> List[IngestResult]:
    """Ingest a file or (recursively) a folder of supported sources.

    progress(src)                    — called before each file (for "ingesting …" line)
    on_result(res, index, total)     — called after each file with result + position
    max_new                          — stop after this many non-cached docs (for batched runs)
    """
    sources = discover_sources(target)
    if not sources:
        return []
    base_dir = target if target.is_dir() else target.parent
    cache = project.load_ingest_cache()
    results: List[IngestResult] = []
    total = len(sources)
    new_count = 0
    for idx, src in enumerate(sources):
        if progress:
            progress(src)
        t0 = time.monotonic()
        res = ingest_file(project, client, src, base_dir=base_dir, cache=cache, embedder=embedder)
        res.elapsed_s = time.monotonic() - t0
        results.append(res)
        if on_result:
            on_result(res, idx + 1, total)
        if not res.skipped:
            new_count += 1
            if max_new is not None and new_count >= max_new:
                break
    return results
