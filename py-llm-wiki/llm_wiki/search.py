"""Hybrid search over wiki pages: keyword scoring + vector similarity, fused
with Reciprocal Rank Fusion (RRF).

Degrades gracefully: with no API key (or no embeddings on disk) it falls back
to keyword-only ranking, matching the "index file is enough at small scale"
idea from the methodology. Mirrors ``src/lib/search.ts`` + ``search-rrf.ts``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .embedding import Embedder
from .store import WikiPage, WikiProject
from .vectorstore import VectorStore

RRF_K = 60  # standard RRF damping constant
WORD_RE = re.compile(r"[\w]+", re.UNICODE)


@dataclass
class SearchHit:
    page: WikiPage
    score: float
    keyword_rank: Optional[int] = None
    vector_rank: Optional[int] = None
    vector_score: Optional[float] = None


def _tokenize(text: str) -> List[str]:
    return [w.lower() for w in WORD_RE.findall(text)]


def keyword_rank(query: str, pages: List[WikiPage]) -> List[Tuple[str, float]]:
    """Rank pages by term-frequency overlap, with a title boost."""
    q_terms = set(_tokenize(query))
    if not q_terms:
        return []
    scored: List[Tuple[str, float]] = []
    for p in pages:
        body_tokens = _tokenize(p.body)
        title_tokens = _tokenize(p.title)
        if not body_tokens and not title_tokens:
            continue
        body_hits = sum(1 for t in body_tokens if t in q_terms)
        title_hits = sum(1 for t in title_tokens if t in q_terms)
        score = body_hits + 3.0 * title_hits  # title matches weigh more
        if score > 0:
            scored.append((p.path, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def search(
    project: WikiProject,
    query: str,
    *,
    embedder: Optional[Embedder] = None,
    k: int = 8,
) -> List[SearchHit]:
    pages = project.iter_pages()
    if not pages:
        return []
    by_path: Dict[str, WikiPage] = {p.path: p for p in pages}

    kw = keyword_rank(query, pages)
    kw_rank = {path: i for i, (path, _) in enumerate(kw)}

    vec_rank: Dict[str, int] = {}
    vec_score: Dict[str, float] = {}
    if embedder is not None:
        store = VectorStore(project.embeddings_path)
        if len(store) > 0:
            try:
                qvec = embedder.embed([query])[0]
                for i, (path, sim) in enumerate(store.search(qvec, k=max(k * 2, 16))):
                    if path in by_path:
                        vec_rank[path] = i
                        vec_score[path] = sim
            except Exception:
                pass  # vector layer is optional

    # Reciprocal Rank Fusion across the two rankings.
    fused: Dict[str, float] = {}
    for path, r in kw_rank.items():
        fused[path] = fused.get(path, 0.0) + 1.0 / (RRF_K + r + 1)
    for path, r in vec_rank.items():
        fused[path] = fused.get(path, 0.0) + 1.0 / (RRF_K + r + 1)

    hits: List[SearchHit] = []
    for path, score in fused.items():
        hits.append(
            SearchHit(
                page=by_path[path],
                score=score,
                keyword_rank=kw_rank.get(path),
                vector_rank=vec_rank.get(path),
                vector_score=vec_score.get(path),
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def search_mode(project: WikiProject, embedder: Optional[Embedder]) -> str:
    """Human-readable description of which retrieval signals are active."""
    if embedder is None:
        return "keyword"
    store = VectorStore(project.embeddings_path)
    return "hybrid" if len(store) > 0 else "keyword"
