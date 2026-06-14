"""FastAPI backend for the desktop GUI.

Exposes the core library over a tiny local JSON API consumed by the bundled
web frontend. Bound to 127.0.0.1 only. Reuses the same WikiProject the CLI
operates on, so the GUI and CLI share one wiki.

This module is only imported in the GUI code path, so it may depend on the
optional GUI packages (fastapi / pydantic) at import time. Note: we do NOT use
``from __future__ import annotations`` here — FastAPI must resolve the real
Pydantic model classes from the annotations, not lazy string forms.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_config
from .store import WikiProject


class SearchReq(BaseModel):
    query: str
    k: int = 8


class QueryReq(BaseModel):
    question: str
    k: int = 8
    save: bool = False


class IngestReq(BaseModel):
    path: str
    embed: bool = True


class IngestLarkReq(BaseModel):
    url: str
    embed: bool = True


def create_app(project: WikiProject) -> FastAPI:
    app = FastAPI(title="LLM Wiki", docs_url=None, redoc_url=None)
    web_dir = Path(__file__).parent / "web"

    def _client_or_none():
        from .llm import LLMClient, LLMError

        cfg = load_config(project.config_path)
        if not cfg.has_llm:
            return None
        try:
            return LLMClient(cfg)
        except LLMError:
            return None

    def _embedder_or_none(client=None):
        from .embedding import get_embedder

        cfg = load_config(project.config_path)
        try:
            return get_embedder(cfg, client)
        except Exception:
            return None

    @app.get("/api/health")
    def health():
        cfg = load_config(project.config_path)
        return {
            "ok": True,
            "root": str(project.root),
            "has_llm": cfg.has_llm,
            "model": cfg.model,
        }

    @app.get("/api/graph")
    def graph():
        from .graph import build_graph

        return build_graph(project)

    @app.get("/api/page")
    def page(path: str):
        wiki_page = project.read_page(path)
        if wiki_page is None:
            raise HTTPException(status_code=404, detail="page not found")
        return {
            "path": wiki_page.path,
            "title": wiki_page.title,
            "type": wiki_page.type,
            "meta": wiki_page.meta,
            "body": wiki_page.body,
        }

    @app.post("/api/search")
    def do_search(req: SearchReq):
        from .search import search, search_mode

        embedder = _embedder_or_none(_client_or_none())
        hits = search(project, req.query, embedder=embedder, k=req.k)
        return {
            "mode": search_mode(project, embedder),
            "results": [
                {
                    "slug": h.page.slug,
                    "title": h.page.title,
                    "type": h.page.type,
                    "path": h.page.path,
                    "score": round(h.score, 4),
                    "vectorScore": h.vector_score,
                }
                for h in hits
            ],
        }

    @app.post("/api/query")
    def do_query(req: QueryReq):
        from .query import query as run_query

        client = _client_or_none()
        if client is None:
            raise HTTPException(status_code=400, detail="No API key. Set OPENAI_API_KEY before starting the GUI.")
        embedder = _embedder_or_none(client)
        result = run_query(project, client, req.question, embedder=embedder, k=req.k, save=req.save)
        return {
            "answer": result.answer,
            "savedPath": result.saved_path,
            "sources": [{"slug": h.page.slug, "path": h.page.path} for h in result.hits],
        }

    @app.post("/api/ingest")
    def do_ingest(req: IngestReq):
        from .ingest import ingest_path

        client = _client_or_none()
        if client is None:
            raise HTTPException(status_code=400, detail="No API key. Set OPENAI_API_KEY before starting the GUI.")
        target = Path(req.path).expanduser()
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"path not found: {target}")
        embedder = _embedder_or_none(client) if req.embed else None
        results = ingest_path(project, client, target, embedder=embedder)
        return {
            "results": [
                {
                    "source": r.source,
                    "skipped": r.skipped,
                    "files": len(r.files_written),
                    "reviews": r.reviews,
                    "error": r.error,
                }
                for r in results
            ]
        }

    @app.post("/api/ingest-lark")
    def do_ingest_lark(req: IngestLarkReq):
        from .lark import LarkError, ingest_lark_wiki, lark_cli_available

        if not lark_cli_available():
            raise HTTPException(status_code=400, detail="lark-cli not found. Install it and run `lark-cli auth login`.")
        client = _client_or_none()
        if client is None:
            raise HTTPException(status_code=400, detail="No API key. Set OPENAI_API_KEY before starting the GUI.")
        embedder = _embedder_or_none(client) if req.embed else None
        try:
            summary = ingest_lark_wiki(project, client, req.url, embedder=embedder)
        except LarkError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "exported": len(summary.export.docs),
            "skipped": len(summary.export.skipped),
            "results": [
                {
                    "source": r.source,
                    "skipped": r.skipped,
                    "files": len(r.files_written),
                    "reviews": r.reviews,
                    "error": r.error,
                }
                for r in summary.results
            ],
        }

    # Static frontend (mounted last so /api/* wins).
    if web_dir.is_dir():
        @app.get("/")
        def index():
            return FileResponse(str(web_dir / "index.html"))

        app.mount("/", StaticFiles(directory=str(web_dir)), name="web")

    return app
