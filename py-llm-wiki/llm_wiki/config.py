"""Project configuration and LLM credential resolution.

Non-secret settings (base_url, model names) live in ``.llm-wiki/config.json``.
The API key is **only** read from the ``OPENAI_API_KEY`` environment variable —
it is never written to disk.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"


@dataclass
class Config:
    base_url: Optional[str] = None
    model: str = DEFAULT_MODEL
    embed_model: str = DEFAULT_EMBED_MODEL
    # "openai" (OpenAI-compatible /chat/completions) or "anthropic" (/v1/messages).
    chat_provider: str = "openai"
    # "openai" (use the /embeddings endpoint) or "fastembed" (local, on-device).
    embed_provider: str = "openai"
    # api_key is resolved at runtime from the environment, never persisted.
    api_key: Optional[str] = field(default=None, repr=False)

    @property
    def has_llm(self) -> bool:
        """True if we have enough to make an LLM call."""
        return bool(self.api_key)

    def to_persistable(self) -> dict:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "embed_model": self.embed_model,
            "chat_provider": self.chat_provider,
            "embed_provider": self.embed_provider,
        }


def load_config(config_path: Path) -> Config:
    """Load config.json (if present), then overlay environment variables.

    Env vars always win, so a user can switch endpoints/models per shell without
    editing files: OPENAI_BASE_URL, LLM_MODEL, EMBED_MODEL, OPENAI_API_KEY.
    """
    data: dict = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

    cfg = Config(
        base_url=data.get("base_url"),
        model=data.get("model", DEFAULT_MODEL),
        embed_model=data.get("embed_model", DEFAULT_EMBED_MODEL),
        chat_provider=data.get("chat_provider", "openai"),
        embed_provider=data.get("embed_provider", "openai"),
    )

    # Environment overrides.
    cfg.base_url = os.environ.get("OPENAI_BASE_URL", cfg.base_url) or None
    cfg.model = os.environ.get("LLM_MODEL", cfg.model)
    cfg.embed_model = os.environ.get("EMBED_MODEL", cfg.embed_model)
    cfg.chat_provider = os.environ.get("LLM_PROVIDER", cfg.chat_provider)
    cfg.embed_provider = os.environ.get("EMBED_PROVIDER", cfg.embed_provider)
    # Key: OPENAI_API_KEY, or fall back to ANTHROPIC_AUTH_TOKEN for gateways.
    cfg.api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")

    return cfg


def save_config(config_path: Path, cfg: Config) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(cfg.to_persistable(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
