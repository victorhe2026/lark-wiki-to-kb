"""Command-line interface for LLM Wiki.

    llm-wiki init   [dir] [--template general]
    llm-wiki ingest [dir] <file|folder> [--no-embed]
    llm-wiki ingest-lark [dir] <wiki-url|token> [--no-embed] [--no-init]
    llm-wiki search [dir] "keywords" [-k 8]
    llm-wiki query  [dir] "question" [--save] [-k 8]
    llm-wiki lint   [dir]
    llm-wiki reindex[dir]
    llm-wiki log    [dir] [-n 10]
    llm-wiki gui    [dir] [--port 8765]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from .config import load_config
from .store import WikiProject
from .templates import TEMPLATES


def _eprint(*args) -> None:
    print(*args, file=sys.stderr)


def _project(dir_arg: Optional[str]) -> WikiProject:
    return WikiProject(Path(dir_arg or ".").expanduser())


def _require_project(project: WikiProject) -> bool:
    if not project.exists():
        _eprint(f"error: no wiki found at {project.root}. Run 'llm-wiki init' there first.")
        return False
    return True


def _make_client(project: WikiProject):
    """Build an LLMClient or print a helpful error and return None."""
    from .llm import LLMClient, LLMError

    cfg = load_config(project.config_path)
    try:
        return LLMClient(cfg)
    except LLMError as exc:
        _eprint(f"error: {exc}")
        return None


def _make_embedder(project: WikiProject, client=None):
    """Build the configured embedder, or None if vector search is unavailable.

    fastembed needs no API key; the openai provider reuses the chat client.
    """
    from .embedding import get_embedder

    cfg = load_config(project.config_path)
    if cfg.embed_provider == "openai" and client is None:
        # Try to build a client so the openai embedder can work.
        client = _make_client(project)
    try:
        return get_embedder(cfg, client)
    except Exception as exc:  # noqa: BLE001
        _eprint(f"warning: embedder unavailable ({exc}); vector search disabled.")
        return None


# ── progress helpers ─────────────────────────────────────────────
def _make_on_result(elapsed_buf: List[float]):
    """Return an on_result callback that prints real-time speed + ETA."""
    def on_result(r, idx: int, total: int) -> None:
        if r.skipped:
            print(f"  ⤳ [{idx}/{total}] {r.source} (cached, skipped)")
            return
        if not r.skipped:
            elapsed_buf.append(r.elapsed_s)
        avg = sum(elapsed_buf) / len(elapsed_buf) if elapsed_buf else 0
        remaining = total - idx
        eta_s = avg * remaining
        eta_str = f"{int(eta_s // 60)}m{int(eta_s % 60):02d}s" if eta_s >= 60 else f"{eta_s:.0f}s"
        if r.error:
            _eprint(
                f"  ✗ [{idx}/{total}] {r.source}: {r.error}"
                f"  ({r.elapsed_s:.1f}s | avg {avg:.1f}s | ETA ~{eta_str})"
            )
        else:
            print(
                f"  ✓ [{idx}/{total}] {r.source}: {len(r.files_written)} pages"
                f"  ({r.elapsed_s:.1f}s | avg {avg:.1f}s | ETA ~{eta_str})"
            )
    return on_result


# ── commands ─────────────────────────────────────────────────────
def cmd_init(args) -> int:
    project = _project(args.dir)
    template = TEMPLATES.get(args.template)
    if template is None:
        _eprint(f"error: unknown template '{args.template}'. Choices: {', '.join(TEMPLATES)}")
        return 2
    project.init(template)
    print(f"Initialized {template.name} wiki at {project.root}")
    print("Next: set OPENAI_API_KEY, then `llm-wiki ingest <file-or-folder>`.")
    return 0


def cmd_ingest(args) -> int:
    project = _project(args.dir)
    if not _require_project(project):
        return 2
    target = Path(args.target).expanduser()
    if not target.exists():
        _eprint(f"error: path not found: {target}")
        return 2
    client = _make_client(project)
    if client is None:
        return 2

    from .ingest import ingest_path

    embedder = None if args.no_embed else _make_embedder(project, client)
    elapsed_buf: List[float] = []

    def progress(src: Path):
        print(f"  ingesting {src.name} ...", flush=True)

    max_new = getattr(args, "limit", None)
    if max_new:
        print(f"  (batch mode: up to {max_new} new docs this run)")
    t_start = time.monotonic()
    results = ingest_path(project, client, target, embedder=embedder,
                          progress=progress, on_result=_make_on_result(elapsed_buf),
                          max_new=max_new)
    if not results:
        _eprint("No supported source files found (.txt/.md).")
        return 1

    ok = sum(1 for r in results if not r.error and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if r.error)
    total_s = time.monotonic() - t_start
    avg = sum(elapsed_buf) / len(elapsed_buf) if elapsed_buf else 0
    print(f"\nDone. {ok} ingested, {skipped} skipped, {failed} failed."
          f"  Total {total_s:.0f}s | avg {avg:.1f}s/doc")
    if max_new and (ok + failed) >= max_new:
        print(f"Batch limit reached ({max_new}). Re-run to continue.")
    return 0 if failed == 0 else 1


def cmd_ingest_lark(args) -> int:
    from .lark import LarkError, ingest_lark_wiki, lark_cli_available

    if not lark_cli_available():
        _eprint("error: lark-cli not found on PATH. Install it and run "
                "`lark-cli auth login`, then retry.")
        return 2

    project = _project(args.dir)
    # "Initial stage" bootstrap: auto-create the wiki if it doesn't exist yet.
    if not project.exists():
        if args.no_init:
            return 2 if not _require_project(project) else 0
        template = TEMPLATES.get(args.template)
        if template is None:
            _eprint(f"error: unknown template '{args.template}'. Choices: {', '.join(TEMPLATES)}")
            return 2
        project.init(template)
        print(f"Initialized {template.name} wiki at {project.root}")

    client = _make_client(project)
    if client is None:
        return 2

    embedder = None if args.no_embed else _make_embedder(project, client)
    elapsed_buf: List[float] = []

    def progress(src):
        name = src if isinstance(src, str) else src.name
        print(f"  ingesting {name} ...", flush=True)

    max_new = getattr(args, "limit", None)
    if max_new:
        print(f"  (batch mode: up to {max_new} new docs this run)")
    print(f"Fetching Lark wiki: {args.wiki} ...")
    try:
        summary = ingest_lark_wiki(project, client, args.wiki, embedder=embedder,
                                   progress=progress, on_result=_make_on_result(elapsed_buf),
                                   max_new=max_new)
    except LarkError as exc:
        _eprint(f"error: {exc}")
        return 1

    export = summary.export
    print(f"Exported {len(export.docs)} document(s) to {export.staging_dir}.")
    if export.skipped:
        types = ", ".join(sorted({n.obj_type or "?" for n in export.skipped}))
        print(f"  Skipped {len(export.skipped)} unsupported node(s) [{types}].")
    for err in export.errors:
        _eprint(f"  ✗ fetch: {err}")

    if not export.docs:
        _eprint("No supported documents (doc/docx) found in this wiki.")
        return 1

    ok = sum(1 for r in summary.results if not r.error and not r.skipped)
    skipped = sum(1 for r in summary.results if r.skipped)
    failed = sum(1 for r in summary.results if r.error)
    avg = sum(elapsed_buf) / len(elapsed_buf) if elapsed_buf else 0
    print(f"\nDone. {ok} ingested, {skipped} skipped, {failed} failed."
          f"  Avg {avg:.1f}s/doc")
    if max_new and (ok + failed) >= max_new:
        print(f"Batch limit reached ({max_new}). Re-run to continue.")
    print("View the knowledge graph with: llm-wiki gui")
    return 0 if failed == 0 else 1


def cmd_search(args) -> int:
    project = _project(args.dir)
    if not _require_project(project):
        return 2
    from .search import search, search_mode

    # Vector search uses the configured embedder (fastembed works with no key);
    # keyword-only is the fallback when no embedder is available.
    embedder = _make_embedder(project)
    mode = search_mode(project, embedder)
    hits = search(project, args.query, embedder=embedder, k=args.k)
    print(f"Search mode: {mode}   ({len(hits)} results)\n")
    if not hits:
        print("No matches.")
        return 0
    for h in hits:
        signals = []
        if h.keyword_rank is not None:
            signals.append("kw")
        if h.vector_rank is not None:
            signals.append(f"vec={h.vector_score:.2f}")
        sig = f" [{', '.join(signals)}]" if signals else ""
        print(f"  {h.score:.4f}  [[{h.page.slug}]]  {h.page.title}  ({h.page.type}){sig}")
        print(f"          {h.page.path}")
    return 0


def cmd_query(args) -> int:
    project = _project(args.dir)
    if not _require_project(project):
        return 2
    client = _make_client(project)
    if client is None:
        return 2
    from .query import query

    embedder = _make_embedder(project, client)
    result = query(project, client, args.question, embedder=embedder, k=args.k, save=args.save)
    print(result.answer)
    if result.hits:
        print("\n--- sources ---")
        for h in result.hits:
            print(f"  [[{h.page.slug}]] ({h.page.path})")
    if result.saved_path:
        print(f"\nSaved answer to {result.saved_path}")
    return 0


def cmd_lint(args) -> int:
    project = _project(args.dir)
    if not _require_project(project):
        return 2
    client = _make_client(project)
    if client is None:
        return 2
    from .lint import lint

    print(lint(project, client))
    return 0


def cmd_reindex(args) -> int:
    project = _project(args.dir)
    if not _require_project(project):
        return 2
    embedder = _make_embedder(project)
    if embedder is None:
        _eprint("error: no embedder available. Set EMBED_PROVIDER=fastembed (local) "
                "or configure an embeddings endpoint + OPENAI_API_KEY.")
        return 2
    from .ingest import reindex_all

    n = reindex_all(project, embedder)
    print(f"Reindexed embeddings for {n} pages ({embedder.name}).")
    return 0


def cmd_config(args) -> int:
    project = _project(args.dir)
    if not _require_project(project):
        return 2
    from .config import load_config, save_config

    cfg = load_config(project.config_path)

    changed = False
    for attr, val in (
        ("base_url", args.base_url),
        ("model", args.model),
        ("chat_provider", args.chat_provider),
        ("embed_provider", args.embed_provider),
        ("embed_model", args.embed_model),
    ):
        if val is not None:
            setattr(cfg, attr, val)
            changed = True

    if changed:
        save_config(project.config_path, cfg)
        print(f"Saved {project.config_path}")

    # Always show the resulting persisted (non-secret) config.
    import json

    print(json.dumps(cfg.to_persistable(), indent=2, ensure_ascii=False))
    key_src = (
        "OPENAI_API_KEY" if os.environ.get("OPENAI_API_KEY")
        else "ANTHROPIC_AUTH_TOKEN" if os.environ.get("ANTHROPIC_AUTH_TOKEN")
        else None
    )
    print(f"\nAPI key: {'found via $' + key_src if key_src else 'NOT set (export OPENAI_API_KEY or ANTHROPIC_AUTH_TOKEN)'}")
    print("(The key is read from the environment only and never written to disk.)")
    return 0


def cmd_log(args) -> int:
    project = _project(args.dir)
    if not _require_project(project):
        return 2
    log = project.read_text("wiki/log.md")
    if not log.strip():
        print("(log is empty)")
        return 0
    entries = [ln for ln in log.splitlines() if ln.startswith("## [")]
    for ln in entries[: args.n]:
        print(ln)
    if not entries:
        print(log)
    return 0


def cmd_gui(args) -> int:
    project = _project(args.dir)
    if not _require_project(project):
        return 2
    try:
        from .gui import launch
    except ImportError as exc:
        _eprint(f"error: GUI dependencies missing ({exc}). Install with: pip install 'llm-wiki[gui]'")
        return 2
    return launch(project, port=args.port)


# ── parser ───────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llm-wiki", description="LLM-maintained personal knowledge base.")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create a new wiki")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.add_argument("--template", default="general", choices=list(TEMPLATES), help="scenario template")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("ingest", help="ingest a file or folder of sources")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.add_argument("target", help="source file or folder to ingest")
    sp.add_argument("--no-embed", action="store_true", help="skip embedding generation")
    sp.add_argument("--limit", type=int, default=None, metavar="N",
                    help="stop after N non-cached docs (for batched runs; re-run to continue)")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("ingest-lark", help="import & ingest a Lark/Feishu wiki (via lark-cli)")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.add_argument("wiki", help="Lark wiki URL or node/space token")
    sp.add_argument("--no-embed", action="store_true", help="skip embedding generation")
    sp.add_argument("--no-init", action="store_true", help="don't auto-create the wiki if missing")
    sp.add_argument("--template", default="general", choices=list(TEMPLATES),
                    help="template used when auto-creating the wiki")
    sp.add_argument("--limit", type=int, default=None, metavar="N",
                    help="stop after N non-cached docs (for batched runs; re-run to continue)")
    sp.set_defaults(func=cmd_ingest_lark)

    sp = sub.add_parser("search", help="hybrid search over wiki pages")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.add_argument("query", help="search keywords")
    sp.add_argument("-k", type=int, default=8, help="number of results")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("query", help="ask a question against the wiki")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.add_argument("question", help="the question to answer")
    sp.add_argument("--save", action="store_true", help="file the answer back as a query page")
    sp.add_argument("-k", type=int, default=8, help="number of pages to retrieve")
    sp.set_defaults(func=cmd_query)

    sp = sub.add_parser("lint", help="health-check the wiki")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.set_defaults(func=cmd_lint)

    sp = sub.add_parser("reindex", help="rebuild all page embeddings")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.set_defaults(func=cmd_reindex)

    sp = sub.add_parser("config", help="view or set persisted model config (no secrets)")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.add_argument("--base-url", dest="base_url", help="LLM endpoint base URL")
    sp.add_argument("--model", help="chat model name")
    sp.add_argument("--chat-provider", dest="chat_provider", choices=["openai", "anthropic"], help="chat API protocol")
    sp.add_argument("--embed-provider", dest="embed_provider", choices=["openai", "fastembed"], help="embedding backend")
    sp.add_argument("--embed-model", dest="embed_model", help="embedding model name")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("log", help="show recent activity")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.add_argument("-n", type=int, default=10, help="number of entries")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("gui", help="open the desktop GUI (graph + search + ingest)")
    sp.add_argument("dir", nargs="?", help="project directory (default: .)")
    sp.add_argument("--port", type=int, default=8765, help="local server port")
    sp.set_defaults(func=cmd_gui)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
