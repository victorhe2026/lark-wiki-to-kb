"""Embedding backends, decoupled from the chat LLM.

The chat model (e.g. Claude via a gateway) and the embedding model can come
from different places. In particular, Anthropic/Claude has no embedding API, so
when the chat endpoint only serves chat models we use a **local** embedder
(fastembed) that needs no network and no API key.

Two backends:
  - ``fastembed``  — on-device ONNX model, fully offline (recommended)
  - ``openai``     — an OpenAI-compatible /embeddings endpoint (via LLMClient)
"""
from __future__ import annotations

from typing import List, Optional, Protocol, Sequence

from .config import Config

# fastembed's small, fast default. ~90MB, downloaded once and cached.
DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> List[List[float]]: ...

    @property
    def name(self) -> str: ...


class FastEmbedEmbedder:
    """Local ONNX embeddings via the `fastembed` package."""

    def __init__(self, model_name: str = DEFAULT_FASTEMBED_MODEL):
        self.model_name = model_name
        self._model = None  # lazy: model download/load happens on first use

    def _ensure(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "fastembed is not installed. Install with: pip install fastembed"
                ) from exc
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        model = self._ensure()
        return [list(map(float, v)) for v in model.embed(list(texts))]

    @property
    def name(self) -> str:
        return f"fastembed:{self.model_name}"


class OpenAIEmbedder:
    """Embeddings via an OpenAI-compatible /embeddings endpoint."""

    def __init__(self, client):
        self._client = client

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        return self._client.embed(texts)

    @property
    def name(self) -> str:
        return f"openai:{self._client.cfg.embed_model}"


def get_embedder(cfg: Config, chat_client=None) -> Optional[Embedder]:
    """Build the configured embedder, or None if vector search is unavailable.

    - provider "fastembed": always available once the package is installed.
    - provider "openai": needs the chat_client (which carries the API key).
    """
    provider = (cfg.embed_provider or "openai").lower()
    if provider == "fastembed":
        model = cfg.embed_model or DEFAULT_FASTEMBED_MODEL
        # If the user left the OpenAI default in place, swap to the fastembed default.
        if model == "text-embedding-3-small":
            model = DEFAULT_FASTEMBED_MODEL
        return FastEmbedEmbedder(model)
    if provider == "openai":
        if chat_client is None:
            return None
        return OpenAIEmbedder(chat_client)
    return None
