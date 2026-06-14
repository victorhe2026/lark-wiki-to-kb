"""A tiny on-disk vector store: ``{page_path: {hash, vector}}`` in JSON.

Deliberately minimal — no LanceDB/Chroma, no native deps. numpy does the
cosine math. Each wiki page's body is embedded once; the content hash lets us
skip re-embedding unchanged pages.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


class VectorStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
        )

    def needs_embedding(self, page_path: str, content_hash: str) -> bool:
        entry = self._data.get(page_path)
        return entry is None or entry.get("hash") != content_hash

    def upsert(self, page_path: str, content_hash: str, vector: List[float]) -> None:
        self._data[page_path] = {"hash": content_hash, "vector": vector}

    def remove_missing(self, valid_paths: set) -> None:
        for key in list(self._data):
            if key not in valid_paths:
                del self._data[key]

    def __contains__(self, page_path: str) -> bool:
        return page_path in self._data

    def __len__(self) -> int:
        return len(self._data)

    def search(self, query_vec: List[float], k: int = 8) -> List[Tuple[str, float]]:
        """Return up to k (page_path, cosine_similarity) pairs, best first."""
        if not self._data:
            return []
        q = np.asarray(query_vec, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        q = q / qn

        scores: List[Tuple[str, float]] = []
        for page_path, entry in self._data.items():
            v = np.asarray(entry.get("vector", []), dtype=np.float32)
            if v.size == 0:
                continue
            vn = np.linalg.norm(v)
            if vn == 0:
                continue
            sim = float(np.dot(q, v / vn))
            scores.append((page_path, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]
