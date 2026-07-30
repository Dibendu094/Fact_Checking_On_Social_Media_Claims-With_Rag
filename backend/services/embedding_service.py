"""
embedding_service.py
====================

Embeds queries using the HuggingFace Inference API (remote, no local model
load) when HF_API_TOKEN is set — recommended for deployment on hosts with
< 4 GB RAM (e.g. Render Standard).

Falls back to loading the model locally via sentence-transformers when the
token is absent — useful for local dev where RAM is plentiful.

Either path produces identical 1024-dim L2-normalised vectors, so the
Pinecone index is fully compatible with both modes.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

import httpx
import numpy as np

from config import settings

logger = logging.getLogger("services.embedding")


class EmbeddingService:
    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "EmbeddingService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._model = None
                    cls._instance._dim = settings.embedding_dimension
        return cls._instance

    # ------------------------------------------------------------------ #
    # HuggingFace Inference API path (no local model needed)
    # ------------------------------------------------------------------ #
    def _hf_encode(self, texts: List[str]) -> List[List[float]]:
        """Call the HF Inference API and return normalised vectors."""
        url = f"https://router.huggingface.co/hf-inference/models/{settings.embedding_model}/pipeline/feature-extraction"
        headers = {"Authorization": f"Bearer {settings.hf_api_token}"}
        payload = {"inputs": texts, "parameters": {"normalize": True}}

        with httpx.Client(timeout=60) as client:
            r = client.post(url, headers=headers, json=payload)

        if r.status_code != 200:
            raise RuntimeError(
                f"HuggingFace Inference API error {r.status_code}: {r.text[:200]}"
            )

        vecs = r.json()
        # Normalise locally as a safety net (HF may skip it for some models).
        result = []
        for v in vecs:
            arr = np.array(v, dtype=np.float32)
            norm = np.linalg.norm(arr)
            result.append((arr / norm if norm > 0 else arr).tolist())
        return result

    # ------------------------------------------------------------------ #
    # Local sentence-transformers path (dev / high-RAM hosts)
    # ------------------------------------------------------------------ #
    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                device = self._detect_device()
                logger.info(
                    "Loading embedding model '%s' on %s (first run ~2.3 GB)...",
                    settings.embedding_model, device,
                )
                self._model = SentenceTransformer(settings.embedding_model, device=device)
                self._dim = self._model.get_sentence_embedding_dimension()
                logger.info("Embedding model ready. dim=%d", self._dim)
        return self._model

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def dimension(self) -> int:
        return self._dim

    def encode_query(self, text: str) -> List[float]:
        """Encode a single search query into a normalised vector."""
        prefixed = f"query: {text}"
        if settings.hf_api_token:
            return self._hf_encode([prefixed])[0]
        model = self._load_model()
        vec = model.encode(
            [prefixed], normalize_embeddings=True, show_progress_bar=False
        )[0]
        return vec.tolist()

    def encode_passages(self, texts: List[str]) -> List[List[float]]:
        """Encode stored documents (uses the ``passage:`` prefix)."""
        prefixed = [f"passage: {t}" for t in texts]
        if settings.hf_api_token:
            return self._hf_encode(prefixed)
        model = self._load_model()
        vecs = model.encode(
            prefixed, normalize_embeddings=True, show_progress_bar=False
        )
        return [v.tolist() for v in vecs]


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()
