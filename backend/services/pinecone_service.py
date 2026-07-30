"""
pinecone_service.py
===================

Thin wrapper around the Pinecone serverless index holding the fact-check
vectors. Connection is lazy so the API can boot without a key.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from config import settings

logger = logging.getLogger("services.pinecone")


class PineconeService:
    _instance: Optional["PineconeService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "PineconeService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._index = None
        return cls._instance

    # ------------------------------------------------------------------ #
    def _connect(self):
        if self._index is not None:
            return self._index
        if not settings.pinecone_api_key:
            raise RuntimeError(
                "PINECONE_API_KEY is not set. Configure backend/.env before "
                "calling the fact-check endpoint."
            )
        with self._lock:
            if self._index is None:
                from pinecone import Pinecone

                pc = Pinecone(api_key=settings.pinecone_api_key)
                logger.info("Connecting to Pinecone index '%s'...",
                            settings.pinecone_index_name)
                self._index = pc.Index(settings.pinecone_index_name)
        return self._index

    # ------------------------------------------------------------------ #
    def search_similar_claims(
        self,
        vector: List[float],
        top_k: Optional[int] = None,
    ) -> List[Dict]:
        """
        Query Pinecone for the nearest claims and return them as plain dicts.
        Results below ``similarity_threshold`` are discarded.
        """
        top_k = top_k or settings.top_k_results
        index = self._connect()

        res = index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True,
            namespace=settings.pinecone_namespace,
        )
        matches = res.get("matches") if isinstance(res, dict) else res.matches

        out: List[Dict] = []
        for m in matches or []:
            md = (m.get("metadata") if isinstance(m, dict) else m.metadata) or {}
            score = float(m.get("score") if isinstance(m, dict) else m.score)
            if score < settings.similarity_threshold:
                continue
            out.append(
                {
                    "claim_text": md.get("claim_text", ""),
                    "verdict": md.get("verdict", "UNVERIFIED"),
                    "category": md.get("category", "Other"),
                    "similarity_score": round(score, 4),
                    "source_url": md.get("source_url", "N/A"),
                    "evidence_url": md.get("evidence_url", "N/A"),
                }
            )
        logger.info("Pinecone returned %d matches (%d above threshold %.2f)",
                    len(matches or []), len(out), settings.similarity_threshold)
        return out

    def index_stats(self) -> Dict:
        index = self._connect()
        stats = index.describe_index_stats()
        if isinstance(stats, dict):
            return stats
        # Convert object form to dict best-effort.
        return {
            "total_vector_count": getattr(stats, "total_vector_count", None),
            "dimension": getattr(stats, "dimension", None),
        }


def get_pinecone_service() -> PineconeService:
    return PineconeService()
