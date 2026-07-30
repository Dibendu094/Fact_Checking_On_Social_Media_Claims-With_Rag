"""
web_search_service.py
=====================

Live evidence lookup, used when the local index has no strong match.

Two layers, tried in order:

* **Layer 1 — Google Fact Check Tools API** (needs ``GOOGLE_API_KEY``).
  Returns structured ClaimReview data: publisher, textual rating, article URL.
  This is the good one: real, citable, published fact-checks.
* **Layer 2 — DuckDuckGo Instant Answer** (no key required).
  Only yields an abstract + source link; treated as weak evidence.

Every call is best-effort: network problems degrade to ``found=False`` rather
than raising, so the pipeline can still answer.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger("services.web_search")

GOOGLE_FC_ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
DDG_ENDPOINT = "https://api.duckduckgo.com/"

_TIMEOUT = 8.0

# Publisher rating text -> our canonical verdict.
_RATING_MAP = {
    "true": "TRUE", "correct": "TRUE", "accurate": "TRUE", "verified": "TRUE",
    "mostly true": "MISLEADING", "half true": "MISLEADING",
    "partly true": "MISLEADING", "partly false": "MISLEADING",
    "mixture": "MISLEADING", "misleading": "MISLEADING",
    "exaggerated": "MISLEADING", "missing context": "MISLEADING",
    "lacks context": "MISLEADING", "altered": "MISLEADING",
    "false": "FALSE", "fake": "FALSE", "incorrect": "FALSE",
    "pants on fire": "FALSE", "debunked": "FALSE", "hoax": "FALSE",
    "fabricated": "FALSE", "no evidence": "FALSE", "scam": "FALSE",
    "unproven": "UNVERIFIED", "unverified": "UNVERIFIED",
    "research in progress": "UNVERIFIED", "outdated": "UNVERIFIED",
}


def _map_rating(text: Optional[str]) -> Optional[str]:
    """Map a publisher's free-text rating onto our 4-verdict vocabulary."""
    if not text:
        return None
    t = str(text).strip().lower()
    if t in _RATING_MAP:
        return _RATING_MAP[t]
    # Longest-key-first substring match so "mostly true" beats "true".
    for key in sorted(_RATING_MAP, key=len, reverse=True):
        if key in t:
            return _RATING_MAP[key]
    return None


class WebSearchService:
    """Stateless helper; safe to construct per request."""

    # ------------------------------------------------------------------ #
    async def search(self, claim: str) -> Dict:
        """
        Look for published fact-checks about ``claim``.

        Returns a dict with: found, verdict, confidence, explanation,
        fact_checker, fact_check_url, sources[], provider.
        """
        empty: Dict = {
            "found": False, "verdict": None, "confidence": 0,
            "explanation": "", "fact_checker": None, "fact_check_url": None,
            "sources": [], "provider": None,
        }
        if not settings.enable_web_search:
            return empty

        if settings.has_google_factcheck():
            try:
                result = await self._google_factcheck(claim)
                if result["found"]:
                    return result
            except Exception as exc:  # noqa: BLE001
                logger.warning("Google Fact Check lookup failed: %s", exc)

        try:
            return await self._duckduckgo(claim)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDuckGo lookup failed: %s", exc)
            return empty

    # ------------------------------------------------------------------ #
    async def _google_factcheck(self, claim: str) -> Dict:
        params = {
            "key": settings.google_api_key,
            "query": claim[:300],
            "languageCode": "en",
            "pageSize": 5,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(GOOGLE_FC_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        claims = data.get("claims") or []
        sources: List[Dict] = []
        top_verdict: Optional[str] = None

        for item in claims:
            for review in item.get("claimReview", []) or []:
                publisher = (review.get("publisher") or {}).get("name", "") or ""
                url = review.get("url", "") or ""
                title = review.get("title") or item.get("text", "") or ""
                rating = review.get("textualRating")
                mapped = _map_rating(rating)
                if top_verdict is None and mapped:
                    top_verdict = mapped
                if url:
                    sources.append({
                        "publisher": publisher,
                        "title": title[:300],
                        "url": url,
                        "verdict": rating,
                    })

        if not sources:
            return {"found": False, "verdict": None, "confidence": 0,
                    "explanation": "", "fact_checker": None,
                    "fact_check_url": None, "sources": [], "provider": "google"}

        top = sources[0]
        logger.info("Google Fact Check: %d source(s) for claim", len(sources))
        return {
            "found": True,
            "verdict": top_verdict,
            # Structured ClaimReview data is strong evidence.
            "confidence": 85 if top_verdict else 55,
            "explanation": (
                f"{top['publisher']} published a fact-check of this claim"
                + (f" rating it \"{top['verdict']}\"." if top.get("verdict") else ".")
            ),
            "fact_checker": top["publisher"],
            "fact_check_url": top["url"],
            "sources": sources[:5],
            "provider": "google_factcheck",
        }

    # ------------------------------------------------------------------ #
    async def _duckduckgo(self, claim: str) -> Dict:
        params = {"q": claim[:300], "format": "json", "no_html": 1,
                  "skip_disambig": 1}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(DDG_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        abstract = (data.get("AbstractText") or "").strip()
        source_url = data.get("AbstractURL") or ""
        source_name = data.get("AbstractSource") or ""

        if not abstract:
            return {"found": False, "verdict": None, "confidence": 0,
                    "explanation": "", "fact_checker": None,
                    "fact_check_url": None, "sources": [], "provider": "duckduckgo"}

        sources = []
        if source_url:
            sources.append({
                "publisher": source_name or "DuckDuckGo",
                "title": (data.get("Heading") or claim)[:300],
                "url": source_url,
                "verdict": None,
            })

        logger.info("DuckDuckGo abstract found (%d chars)", len(abstract))
        return {
            "found": True,
            # An encyclopaedic abstract is context, not a verdict.
            "verdict": None,
            "confidence": 35,
            "explanation": abstract[:600],
            "fact_checker": source_name or None,
            "fact_check_url": source_url or None,
            "sources": sources,
            "provider": "duckduckgo",
        }


_service: Optional[WebSearchService] = None


def get_web_search_service() -> WebSearchService:
    global _service
    if _service is None:
        _service = WebSearchService()
    return _service
