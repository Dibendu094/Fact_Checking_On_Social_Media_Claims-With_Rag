"""
rag_pipeline.py
===============

Orchestrates the retrieval-augmented fact-check with a 3-tier routing strategy
based on how well the local index matches the incoming claim:

    Tier 1  HIGH      top similarity >= HIGH_CONF_THRESHOLD (0.88)
                      -> index evidence only, no web call (fast path)
    Tier 2  MEDIUM    >= MEDIUM_CONF_THRESHOLD (0.86)
                      -> index evidence only (partial match, still no web call)
    Tier 3  LOW       below that -> live web search is the primary evidence
    Tier 4  VERY_LOW  nothing found anywhere -> answer is a starting point only

Web search is deliberately confined to Tier 3 so the common path stays fast
and does not consume search-API quota.

Thresholds are calibrated for multilingual-e5-large, which compresses cosine
similarity into a narrow high band: unrelated text still scores ~0.83-0.85 and
genuine matches land ~0.88+. Generic 0.80/0.60 cut-offs would send every claim
to Tier 1.

Heavy/blocking calls (encode, Pinecone, Groq) run in a threadpool so the
FastAPI event loop stays responsive; the web lookup is natively async.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

from config import settings
from services.embedding_service import get_embedding_service
from services.groq_service import get_groq_service
from services.pinecone_service import get_pinecone_service
from services.web_search_service import get_web_search_service

logger = logging.getLogger("services.rag")

TIER_REASONS = {
    "HIGH": "Close match against published fact-checks in the index.",
    "MEDIUM": "Partial match against published fact-checks in the index.",
    "LOW": "No close index match; checked against live sources.",
    "VERY_LOW": "No matching fact-check found in the index or on the web.",
}


class RAGPipeline:
    def __init__(self) -> None:
        self.embedder = get_embedding_service()
        self.pinecone = get_pinecone_service()
        self.llm = get_groq_service()
        self.web = get_web_search_service()

    # ------------------------------------------------------------------ #
    async def fact_check(self, claim: str) -> Dict:
        start = time.time()
        claim = claim.strip()

        # 1) Encode + retrieve from the local index.
        vector = await asyncio.to_thread(self.embedder.encode_query, claim)
        try:
            similar = await asyncio.to_thread(
                self.pinecone.search_similar_claims, vector, settings.top_k_results
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Pinecone search failed: %s", exc)
            similar = []

        top_score = max((s["similarity_score"] for s in similar), default=0.0)

        # 2) Route to a tier and gather web evidence when needed.
        tier = self._route(top_score)
        web: Dict = {"found": False, "sources": [], "verdict": None,
                     "confidence": 0, "explanation": "", "fact_checker": None,
                     "fact_check_url": None}

        # Web search fires ONLY at Tier 3 (LOW): Tier 1 and Tier 2 answer from
        # the index alone, which keeps the common path fast and quota-free.
        if tier == "LOW" and settings.enable_web_search:
            web = await self.web.search(claim)

        # Nothing anywhere -> VERY_LOW.
        if not similar and not web.get("found"):
            tier = "VERY_LOW"

        # 3) Ask the LLM (Groq) to reason over whatever evidence we have.
        llm = await asyncio.to_thread(
            self.llm.generate_verdict, claim, similar, self._web_context(web)
        )

        # 4) Merge verdicts + confidence according to the tier.
        verdict, confidence = self._merge(tier, llm, similar, web, top_score)

        elapsed_ms = int((time.time() - start) * 1000)
        sources = web.get("sources") or []
        logger.info(
            "Fact-check %dms | tier=%s top_sim=%.3f verdict=%s conf=%d "
            "index=%d web=%s",
            elapsed_ms, tier, top_score, verdict, confidence,
            len(similar), bool(web.get("found")),
        )

        return {
            "claim": claim,
            "verdict": verdict,
            "confidence": confidence,
            "explanation": llm.get("explanation", ""),
            "key_points": llm.get("key_points", []),
            "recommendation": llm.get("recommendation", ""),
            "similar_claims": similar,
            "processing_time_ms": elapsed_ms,
            "confidence_tier": tier,
            "tier_reason": TIER_REASONS[tier],
            "web_search_used": tier == "LOW" and settings.enable_web_search,
            "sources": sources,
            "fact_check_url": web.get("fact_check_url"),
            "fact_checker_org": web.get("fact_checker"),
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def _route(top_score: float) -> str:
        if top_score >= settings.high_conf_threshold:
            return "HIGH"
        if top_score >= settings.medium_conf_threshold:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _web_context(web: Dict) -> Optional[str]:
        """Render web findings as a short text block for the LLM prompt."""
        if not web.get("found"):
            return None
        lines = []
        if web.get("explanation"):
            lines.append(web["explanation"])
        for s in (web.get("sources") or [])[:5]:
            rating = f" — rated \"{s['verdict']}\"" if s.get("verdict") else ""
            lines.append(f"- {s.get('publisher', '')}: {s.get('title', '')}{rating}")
        return "\n".join(lines) if lines else None

    @staticmethod
    def _merge(tier: str, llm: Dict, similar: List[Dict], web: Dict,
               top_score: float) -> tuple:
        """
        Combine the LLM verdict with retrieval/web evidence.

        The published fact-check rating (when present) is the strongest signal
        and wins ties; otherwise the LLM's verdict stands and confidence is
        blended with the evidence strength for the tier.
        """
        llm_verdict = llm.get("verdict", "UNVERIFIED")
        llm_conf = float(llm.get("confidence", 0))
        web_verdict = web.get("verdict")

        verdict = llm_verdict
        if web_verdict and llm_verdict == "UNVERIFIED":
            # Prefer a real publisher rating over an LLM shrug.
            verdict = web_verdict

        if tier == "HIGH":
            retrieval_conf = top_score * 100.0
            confidence = (llm_conf + retrieval_conf) / 2.0
        elif tier == "MEDIUM":
            # Index-only, partial match: discount slightly versus Tier 1.
            retrieval_conf = top_score * 100.0
            confidence = ((llm_conf + retrieval_conf) / 2.0) * 0.9
        elif tier == "LOW":
            if web.get("found"):
                confidence = (llm_conf + float(web.get("confidence", 0))) / 2.0
            else:
                confidence = llm_conf * 0.6
        else:  # VERY_LOW
            confidence = llm_conf * 0.5

        # Agreement between an index consensus and the LLM adds confidence.
        if similar:
            agree = sum(1 for s in similar if s["verdict"] == verdict)
            if agree >= max(2, len(similar) // 2):
                confidence = min(100.0, confidence + 5.0)

        return verdict, max(0, min(100, int(round(confidence))))


_pipeline: Optional[RAGPipeline] = None


def get_rag_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RAGPipeline()
    return _pipeline
