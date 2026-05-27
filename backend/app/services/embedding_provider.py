"""Centralized embedding provider abstraction.

Provider selection is driven by env vars and falls back gracefully:

    EMBEDDING_PROVIDER     bge | openai | ollama | hashed   (default: bge)
    EMBEDDING_MODEL        provider-specific model name      (default: BAAI/bge-m3)
    OPENAI_API_KEY         only when provider=openai
    OLLAMA_URL             only when provider=ollama  (default: http://host.docker.internal:11434)

The default chain is **bge → openai → ollama → hashed**: if the configured
primary provider raises (model not loaded, API key missing, connection refused)
we try the next one and remember the failure for the rest of the process so we
don't hammer dead endpoints on every request.

The previous embedding path in ``vector_knowledge.py`` always landed on the
hashed fallback because Groq does not actually expose an embeddings API; this
module replaces that broken path entirely.
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from typing import Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Hashed fallback (kept for emergencies — never used in normal operation).    #
# --------------------------------------------------------------------------- #
_HASHED_DIM = 256


def _hashed_embedding(text: str) -> List[float]:
    """Last-resort deterministic embedding. Token bucket hashing — almost no
    semantic signal but always returns *something* with the right shape."""
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    vec = [0.0] * _HASHED_DIM
    if not tokens:
        return vec

    for token in tokens:
        h = hash(token)
        idx = abs(h) % _HASHED_DIM
        sign = -1.0 if (h % 2 == 0) else 1.0
        vec[idx] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


# --------------------------------------------------------------------------- #
# Sentence-transformers (bge / minilm / mpnet / etc.)                          #
# --------------------------------------------------------------------------- #
class _SentenceTransformersProvider:
    """Thin wrapper around sentence-transformers that loads the model lazily.

    Model loading can take 30-90 seconds for bge-m3 (downloads ~2 GB on first
    run). We do it on the first ``embed`` call rather than at import time so
    the API still boots quickly and so workers that never embed (e.g. health
    checks) never pay the cost.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        self._load_failed = False
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if self._load_failed:
            return False
        with self._lock:
            if self._model is not None:
                return True
            if self._load_failed:
                return False
            try:
                # Imported lazily so the rest of the app doesn't pay the
                # ~3 second torch import cost when this provider is unused.
                from sentence_transformers import SentenceTransformer
                logger.info("[Embedding] Loading sentence-transformers model %s ...", self.model_name)
                self._model = SentenceTransformer(self.model_name)
                logger.info(
                    "[Embedding] Loaded %s (dim=%d)",
                    self.model_name,
                    self._model.get_sentence_embedding_dimension(),
                )
                return True
            except Exception as exc:
                self._load_failed = True
                logger.warning("[Embedding] Failed to load %s: %s", self.model_name, exc)
                return False

    def embed(self, text: str) -> Optional[List[float]]:
        if not self._ensure_loaded():
            return None
        try:
            vec = self._model.encode(
                text[:8000],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return [float(v) for v in vec]
        except Exception as exc:
            logger.warning("[Embedding] sentence-transformers encode failed: %s", exc)
            return None

    def embed_batch(self, texts: Iterable[str]) -> Optional[List[List[float]]]:
        if not self._ensure_loaded():
            return None
        try:
            arr = self._model.encode(
                [t[:8000] for t in texts],
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=16,
            )
            return [[float(v) for v in row] for row in arr]
        except Exception as exc:
            logger.warning("[Embedding] sentence-transformers batch encode failed: %s", exc)
            return None


# --------------------------------------------------------------------------- #
# OpenAI                                                                       #
# --------------------------------------------------------------------------- #
class _OpenAIProvider:
    """OpenAI embeddings via plain HTTP (no SDK dependency)."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._disabled = False

    def embed(self, text: str) -> Optional[List[float]]:
        if self._disabled:
            return None
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self._disabled = True
            return None
        try:
            resp = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model_name, "input": text[:8000]},
                timeout=float(os.getenv("OPENAI_EMBEDDING_TIMEOUT_SEC", "10")),
            )
            if resp.status_code == 200:
                data = resp.json()
                emb = data.get("data", [{}])[0].get("embedding")
                if isinstance(emb, list) and emb:
                    return [float(v) for v in emb]
            # Permanent config errors — disable to avoid hammering.
            if resp.status_code in {400, 401, 403, 404, 422}:
                self._disabled = True
                logger.warning("[Embedding] OpenAI returned %s, disabling for this process", resp.status_code)
        except Exception as exc:
            logger.debug("[Embedding] OpenAI request failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# OpenRouter                                                                  #
# --------------------------------------------------------------------------- #
class _OpenRouterProvider:
    """OpenRouter embeddings (gateway to OpenAI, Cohere, etc.)."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._disabled = False

    def embed(self, text: str) -> Optional[List[float]]:
        if self._disabled:
            return None
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            self._disabled = True
            return None
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model_name, "input": text[:8000]},
                timeout=float(os.getenv("OPENROUTER_EMBEDDING_TIMEOUT_SEC", "10")),
            )
            if resp.status_code == 200:
                data = resp.json()
                emb = data.get("data", [{}])[0].get("embedding")
                if isinstance(emb, list) and emb:
                    return [float(v) for v in emb]
            if resp.status_code in {400, 401, 403, 404, 422}:
                self._disabled = True
                logger.warning("[Embedding] OpenRouter returned %s, disabling for this process", resp.status_code)
        except Exception as exc:
            logger.debug("[Embedding] OpenRouter request failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Ollama                                                                       #
# --------------------------------------------------------------------------- #
class _OllamaProvider:
    """Ollama embeddings (e.g. nomic-embed-text running locally)."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._disabled = False

    def embed(self, text: str) -> Optional[List[float]]:
        if self._disabled:
            return None
        url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
        try:
            resp = requests.post(
                f"{url}/api/embeddings",
                json={"model": self.model_name, "prompt": text[:8000]},
                timeout=float(os.getenv("OLLAMA_EMBEDDING_TIMEOUT_SEC", "5")),
            )
            if resp.status_code == 200:
                emb = resp.json().get("embedding")
                if isinstance(emb, list) and emb:
                    return [float(v) for v in emb]
        except Exception as exc:
            logger.debug("[Embedding] Ollama request failed: %s", exc)
            self._disabled = True
        return None


# --------------------------------------------------------------------------- #
# Public service                                                               #
# --------------------------------------------------------------------------- #
class EmbeddingService:
    """Process-wide embedding service. Pick a provider by env, with fallback."""

    _instance: Optional["EmbeddingService"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        provider = (os.getenv("EMBEDDING_PROVIDER") or "bge").strip().lower()
        model = os.getenv("EMBEDDING_MODEL") or self._default_model_for(provider)

        # Build the provider chain in priority order. The first one that
        # returns a non-None vector wins for any given embed() call.
        self._chain: List = []
        self._labels: List[str] = []

        if provider == "bge" or provider == "sentence-transformers":
            self._chain.append(_SentenceTransformersProvider(model))
            self._labels.append(f"sentence-transformers:{model}")
        elif provider == "openai":
            self._chain.append(_OpenAIProvider(model))
            self._labels.append(f"openai:{model}")
        elif provider == "ollama":
            self._chain.append(_OllamaProvider(model))
            self._labels.append(f"ollama:{model}")
        elif provider == "openrouter":
            self._chain.append(_OpenRouterProvider(model))
            self._labels.append(f"openrouter:{model}")
        elif provider == "hashed":
            # Explicit hashed-only mode (testing).
            self._labels.append("hashed")
        else:
            logger.warning("[Embedding] Unknown EMBEDDING_PROVIDER=%s — falling back to bge", provider)
            self._chain.append(_SentenceTransformersProvider("BAAI/bge-m3"))
            self._labels.append("sentence-transformers:BAAI/bge-m3")

        # Always keep an OpenAI / OpenRouter / Ollama secondary path if env vars are set,
        # in case the primary fails silently.
        if provider != "openai" and os.getenv("OPENAI_API_KEY"):
            self._chain.append(_OpenAIProvider(os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")))
            self._labels.append("openai:secondary")
        if provider != "openrouter" and os.getenv("OPENROUTER_API_KEY"):
            self._chain.append(_OpenRouterProvider(os.getenv("OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small")))
            self._labels.append("openrouter:secondary")
        if provider != "ollama":
            # Keep Ollama as a quiet tertiary — only used if it's actually up.
            self._chain.append(_OllamaProvider(os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")))
            self._labels.append("ollama:secondary")

        self._primary_label = self._labels[0] if self._labels else "hashed"
        logger.info("[Embedding] Provider chain: %s", " -> ".join(self._labels + ["hashed(last-resort)"]))

    @staticmethod
    def _default_model_for(provider: str) -> str:
        return {
            "bge": "BAAI/bge-m3",
            "sentence-transformers": "BAAI/bge-m3",
            "openai": "text-embedding-3-small",
            "openrouter": "openai/text-embedding-3-small",
            "ollama": "nomic-embed-text",
            "hashed": "hashed",
        }.get(provider, "BAAI/bge-m3")

    @classmethod
    def instance(cls) -> "EmbeddingService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def primary_label(self) -> str:
        return self._primary_label

    def embed(self, text: str) -> List[float]:
        """Return an embedding vector, never raising. Empty/whitespace input
        returns a zero vector of the hashed-fallback dimension."""
        if not text or not text.strip():
            return [0.0] * _HASHED_DIM

        for provider in self._chain:
            vec = provider.embed(text)
            if vec:
                return vec

        # Truly nothing worked — emit a single warning per process to flag a
        # misconfiguration. The hashed vector still keeps the pipeline alive.
        if not getattr(self, "_warned_hashed", False):
            logger.warning(
                "[Embedding] All providers in chain (%s) failed; falling back to hashed",
                self._primary_label,
            )
            self._warned_hashed = True
        return _hashed_embedding(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batched encode for indexing. Falls through to per-item embed() if
        the primary provider doesn't support batching."""
        if not texts:
            return []

        primary = self._chain[0] if self._chain else None
        if primary is not None and hasattr(primary, "embed_batch"):
            batch = primary.embed_batch(texts)
            if batch is not None:
                return batch

        # Per-item fallback through the full chain.
        return [self.embed(t) for t in texts]
