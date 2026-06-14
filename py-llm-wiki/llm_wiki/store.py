"""WikiProject — filesystem layout and page I/O for one wiki.

Encapsulates the three-layer architecture on disk: raw sources (immutable),
the wiki (LLM-generated markdown), and the schema/purpose config. Also owns the
``.llm-wiki/`` app-state directory (config, ingest cache, embeddings, reviews).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import frontmatter
from .templates import WikiTemplate, get_template

WIKI_SUBDIRS = [
    "wiki/entities",
    "wiki/concepts",
    "wiki/sources",
    "wiki/queries",
    "wiki/comparisons",
    "wiki/synthesis",
]

APP_DIR = ".llm-wiki"


def today_str() -> str:
    return _dt.date.today().isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class WikiPage:
    path: str  # relative to project root, e.g. "wiki/entities/openai.md"
    meta: Dict
    body: str

    @property
    def slug(self) -> str:
        return Path(self.path).stem

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.slug)

    @property
    def type(self) -> str:
        return str(self.meta.get("type") or "concept")


class WikiProject:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # ── paths ────────────────────────────────────────────────────
    @property
    def wiki_dir(self) -> Path:
        return self.root / "wiki"

    @property
    def sources_dir(self) -> Path:
        return self.root / "raw" / "sources"

    @property
    def app_dir(self) -> Path:
        return self.root / APP_DIR

    @property
    def config_path(self) -> Path:
        return self.app_dir / "config.json"

    @property
    def ingest_cache_path(self) -> Path:
        return self.app_dir / "ingest-cache.json"

    @property
    def embeddings_path(self) -> Path:
        return self.app_dir / "embeddings.json"

    @property
    def reviews_path(self) -> Path:
        return self.app_dir / "reviews.md"

    def exists(self) -> bool:
        return self.wiki_dir.is_dir() and (self.root / "schema.md").exists()

    # ── init ─────────────────────────────────────────────────────
    def init(self, template: WikiTemplate) -> None:
        """Create the directory skeleton and seed files for a new wiki."""
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.app_dir.mkdir(parents=True, exist_ok=True)
        for sub in WIKI_SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        for extra in template.extra_dirs:
            (self.root / extra).mkdir(parents=True, exist_ok=True)

        self._write_if_absent(self.root / "schema.md", template.schema)
        self._write_if_absent(self.root / "purpose.md", template.purpose)

        today = today_str()
        self._write_if_absent(
            self.wiki_dir / "index.md",
            f"---\ntype: overview\ntitle: Index\ncreated: {today}\nupdated: {today}\n---\n\n"
            "# Index\n\nContent catalog of this wiki, grouped by type.\n",
        )
        self._write_if_absent(
            self.wiki_dir / "log.md",
            "# Log\n\nChronological record of ingests, queries, and lint passes.\n",
        )
        self._write_if_absent(
            self.wiki_dir / "overview.md",
            f"---\ntype: overview\ntitle: Overview\ncreated: {today}\nupdated: {today}\n---\n\n"
            "# Overview\n\nA high-level summary of everything this wiki covers. "
            "This is regenerated as sources are ingested.\n",
        )
        # Obsidian compatibility marker (empty config dir).
        (self.root / ".obsidian").mkdir(exist_ok=True)

    @staticmethod
    def _write_if_absent(path: Path, content: str) -> None:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    # ── reading config / special files ───────────────────────────
    def read_text(self, rel: str) -> str:
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def read_schema(self) -> str:
        return self.read_text("schema.md")

    def read_purpose(self) -> str:
        return self.read_text("purpose.md")

    def read_index(self) -> str:
        return self.read_text("wiki/index.md")

    def read_overview(self) -> str:
        return self.read_text("wiki/overview.md")

    # ── safe page writing ────────────────────────────────────────
    def _safe_wiki_path(self, rel_path: str) -> Optional[Path]:
        """Resolve an LLM-provided path, rejecting anything outside wiki/.

        The path comes from generated text, so it could contain traversal
        (``../``) or absolute components. We confine all writes to wiki/.
        """
        rel = rel_path.strip().lstrip("/")
        if not rel.endswith(".md"):
            rel = rel + ".md"
        candidate = (self.root / rel).resolve()
        try:
            candidate.relative_to(self.wiki_dir.resolve())
        except ValueError:
            return None
        return candidate

    def write_block(self, rel_path: str, content: str) -> Optional[str]:
        """Write a generated FILE block to disk. Returns the relative path written, or None if rejected."""
        target = self._safe_wiki_path(rel_path)
        if target is None:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
        return str(target.relative_to(self.root))

    def append_log(self, entry: str) -> None:
        log = self.wiki_dir / "log.md"
        existing = log.read_text(encoding="utf-8") if log.exists() else "# Log\n"
        entry = entry.strip()
        # Newest entries directly under the heading (reverse chronological).
        if existing.startswith("# Log"):
            head, _, rest = existing.partition("\n")
            new = f"{head}\n\n{entry}\n{rest.lstrip()}"
        else:
            new = f"{entry}\n\n{existing}"
        log.write_text(new, encoding="utf-8")

    # ── listing / loading pages ──────────────────────────────────
    def iter_pages(self) -> List[WikiPage]:
        """Load all wiki/*.md pages (excluding log.md) as WikiPage objects."""
        pages: List[WikiPage] = []
        if not self.wiki_dir.is_dir():
            return pages
        for p in sorted(self.wiki_dir.rglob("*.md")):
            if p.name == "log.md":
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            meta, body = frontmatter.parse(text)
            rel = str(p.relative_to(self.root))
            pages.append(WikiPage(path=rel, meta=meta, body=body))
        return pages

    def read_page(self, rel_path: str) -> Optional[WikiPage]:
        p = self.root / rel_path
        if not p.exists():
            return None
        meta, body = frontmatter.parse(p.read_text(encoding="utf-8", errors="replace"))
        return WikiPage(path=rel_path, meta=meta, body=body)

    # ── ingest cache ─────────────────────────────────────────────
    def load_ingest_cache(self) -> Dict[str, str]:
        if self.ingest_cache_path.exists():
            try:
                return json.loads(self.ingest_cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save_ingest_cache(self, cache: Dict[str, str]) -> None:
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.ingest_cache_path.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def copy_source(self, src: Path, rel_name: str) -> Path:
        """Copy a source into raw/sources/ preserving a relative sub-path."""
        dest = self.sources_dir / rel_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        return dest

    def append_reviews(self, lines: str) -> None:
        self.app_dir.mkdir(parents=True, exist_ok=True)
        with self.reviews_path.open("a", encoding="utf-8") as fh:
            fh.write(lines.rstrip("\n") + "\n")
