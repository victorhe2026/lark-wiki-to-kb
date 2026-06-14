"""Source document loaders.

MVP supports plain-text formats (.txt / .md / .markdown). The dispatch table
is the single extension point: to add PDF/DOCX later, register a reader here
(e.g. ``pypdf`` / ``python-docx``) — nothing else changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List

SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".text"}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# extension -> reader. Add new formats here.
_READERS: Dict[str, Callable[[Path], str]] = {
    ext: _read_text for ext in SUPPORTED_EXTENSIONS
}


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in _READERS


def read_source(path: Path) -> str:
    """Return the textual content of a source file."""
    ext = path.suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        raise ValueError(
            f"Unsupported source type '{ext}'. Supported: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )
    return reader(path)


def discover_sources(target: Path) -> List[Path]:
    """Expand a file or folder into a sorted list of supported source files."""
    if target.is_file():
        return [target] if is_supported(target) else []
    if target.is_dir():
        found = [p for p in sorted(target.rglob("*")) if p.is_file() and is_supported(p)]
        return found
    return []
