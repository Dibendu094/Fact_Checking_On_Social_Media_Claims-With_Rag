"""
embedding_service.py
====================

Singleton wrapper around the multilingual-e5-large sentence-transformer.

* The model (~2.3 GB) is loaded lazily on first use and only once.
* Queries are prefixed with ``query: `` as required by the e5 family.
* Embeddings are L2-normalized (recommended for cosine similarity).
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from config import settings

logger = logging.getLogger("services.embedding")


class EmbeddingService:
    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "EmbeddingService":
        # Thread-safe singleton.
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._model = None
                    cls._instance._dim = settings.embedding_dimension
        return cls._instance

    # ------------------------------------------------------------------ #
    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                device = self._detect_device()
                logger.info(
                    "Loading embedding model '%s' on %s (first run downloads ~2.3GB)...",
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
    @property
    def dimension(self) -> int:
        return self._dim

    def encode_query(self, text: str) -> List[float]:
        """Encode a single search query into a normalized vector."""
        model = self._load_model()
        vec = model.encode(
            [f"query: {text}"],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return vec.tolist()

    def encode_passages(self, texts: List[str]) -> List[List[float]]:
        """Encode stored documents (uses the ``passage: `` prefix)."""
        model = self._load_model()
        vecs = model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vecs]


# Module-level accessor.
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()
