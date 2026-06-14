"""Thin wrapper over an OpenAI-compatible chat + embeddings endpoint.

Works against the official OpenAI API or any compatible server (Azure-style
deployments, local servers, proxies) by setting ``OPENAI_BASE_URL``. The
``openai`` package is imported lazily so the pure-logic modules and offline
tests don't require it to be installed.
"""
from __future__ import annotations

import time
from typing import List, Sequence

from .config import Config


class LLMError(RuntimeError):
    pass


# Max output tokens for the Anthropic Messages API (which requires the field).
ANTHROPIC_MAX_TOKENS = 4096
ANTHROPIC_VERSION = "2023-06-01"


class LLMClient:
    def __init__(self, cfg: Config):
        if not cfg.api_key:
            raise LLMError(
                "No API key found. Set OPENAI_API_KEY (or ANTHROPIC_AUTH_TOKEN) "
                "in the environment."
            )
        self.cfg = cfg
        self.provider = (cfg.chat_provider or "openai").lower()
        self._client = None
        if self.provider == "openai":
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - import guard
                raise LLMError(
                    "The 'openai' package is required. Install with: pip install openai"
                ) from exc
            kwargs = {"api_key": cfg.api_key}
            if cfg.base_url:
                kwargs["base_url"] = cfg.base_url
            self._client = OpenAI(**kwargs)

    def chat(self, system: str, user: str, *, temperature: float = 0.3) -> str:
        """Single-turn chat. Returns the assistant message text."""
        if self.provider == "anthropic":
            return self._chat_anthropic(system, user, temperature)
        return self._chat_openai(system, user, temperature)

    def _chat_openai(self, system: str, user: str, temperature: float) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self.cfg.model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:  # network/auth/etc.
            raise LLMError(f"Chat completion failed: {exc}") from exc
        content = resp.choices[0].message.content
        return content or ""

    def _chat_anthropic(self, system: str, user: str, temperature: float) -> str:
        """Call the Anthropic Messages API (e.g. a LiteLLM gateway).

        Uses httpx (bundled with openai) so no extra dependency is needed.
        Auth is ``Authorization: Bearer`` only — some gateways' edge/WAF reject
        requests that also carry ``x-api-key`` (observed as an nginx 403).
        Set ``LLM_AUTH_HEADER=x-api-key`` to switch to key-style auth instead.

        Retries up to 3 times with exponential backoff on transient errors
        (network failures, timeouts, 429 rate-limit, 5xx gateway errors, and
        403s that indicate a brief VPN/auth blip rather than a hard rejection).
        """
        import os

        import httpx

        base = (self.cfg.base_url or "https://api.anthropic.com").rstrip("/")
        if base.endswith("/v1"):  # SDK-style root expected; we append /v1/messages
            base = base[: -len("/v1")]
        url = f"{base}/v1/messages"
        headers = {
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        if os.environ.get("LLM_AUTH_HEADER", "bearer").lower() == "x-api-key":
            headers["x-api-key"] = self.cfg.api_key
        else:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        payload = {
            "model": self.cfg.model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        _RETRYABLE = {403, 429, 500, 502, 503, 504}
        last_exc: Exception | None = None
        for attempt in range(4):  # 1 try + 3 retries
            if attempt:
                time.sleep(10 * attempt)  # 10s, 20s, 30s
            try:
                resp = httpx.post(url, headers=headers, json=payload, timeout=240.0)
                if resp.status_code in _RETRYABLE:
                    last_exc = Exception(f"HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                data = resp.json()
                parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
                return "".join(parts)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                continue
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                continue
            except Exception as exc:
                last_exc = exc
                continue

        raise LLMError(f"Chat completion failed: {last_exc}") from last_exc

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed a batch of texts. Returns one vector per input."""
        if not texts:
            return []
        try:
            resp = self._client.embeddings.create(
                model=self.cfg.embed_model,
                input=list(texts),
            )
        except Exception as exc:
            raise LLMError(f"Embedding failed: {exc}") from exc
        # Preserve input order.
        items = sorted(resp.data, key=lambda d: d.index)
        return [list(item.embedding) for item in items]
