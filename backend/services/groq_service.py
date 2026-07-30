"""
groq_service.py
===============

LLM verdict generation via Groq (OpenAI-compatible chat completions, default
model ``llama-3.3-70b-versatile``). Given a user claim plus similar database
claims (and optional live web evidence) it returns a structured verdict dict.
Robust to markdown-fenced JSON and to LLM failures (falls back to UNVERIFIED).

The RAG pipeline's sole LLM provider.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Dict, List, Optional

from config import settings

logger = logging.getLogger("services.groq")

_PROMPT_TEMPLATE = """You explain fact-checks in plain, everyday language — like you're \
telling a friend, not writing a textbook. A 10th grader should understand WHY in under \
10 seconds.

USER CLAIM:
"{claim}"

DATABASE MATCHES (similar previously fact-checked claims, most similar first):
{context}
{web_block}
Assess the claim using the evidence above and your own knowledge. Follow these rules
strictly:

BANNED — do not write any of these words/phrases or close equivalents, anywhere in your
answer: "no credible evidence", "lacks credible corroboration", "similar claims",
"other claims", "have been debunked", "complex condition", "scientific basis",
"scientific consensus", "primary sources contradict". Never mention "the database",
"sources", or "matches" — those are internal, not something to tell the reader about.
Every sentence must be concrete and specific to THIS claim — name the actual substance,
event, technology, or promise involved, and say plainly what it does or doesn't do.

Respond with ONLY a JSON object (no prose, no markdown fences) of this exact shape:
{{
  "verdict": "TRUE | FALSE | MISLEADING | UNVERIFIED",
  "confidence": <integer 0-100>,
  "explanation": "<ONE short, specific, plain-language sentence - the headline reason why>",
  "key_points": [
    "<what the claim says or promises, in plain words>",
    "<what's actually true, specific to this exact topic>",
    "<why it's false/misleading, or a practical takeaway - optional 3rd point>"
  ],
  "recommendation": "<one short, practical, actionable sentence for the reader>"
}}
Each key_points entry is ONE sentence, two at most. No jargon. Never say "other claims",
"similar cases", or "the database" — talk only about the real-world facts of this claim.
Before you answer, check every sentence against the BANNED list above and rewrite any
sentence that breaks it.

TWO EXAMPLES OF THE REQUIRED TONE AND SPECIFICITY:

Claim: "Drinking warm lemon water every morning cures diabetes"
{{
  "verdict": "FALSE",
  "confidence": 95,
  "explanation": "Lemon water gives you vitamin C and hydration, but it cannot cure diabetes.",
  "key_points": [
    "Lemon water has vitamin C and helps with hydration, but it has no effect on blood sugar or insulin.",
    "Diabetes is managed with medicine, diet, and exercise - not a single drink.",
    "If you have diabetes, talk to your doctor about proven treatments."
  ],
  "recommendation": "See a doctor for real, tested diabetes treatment instead of relying on lemon water."
}}

Claim: "NASA faked the moon landing"
{{
  "verdict": "FALSE",
  "confidence": 97,
  "explanation": "The moon landing left behind physical proof still used today, like mirrors that reflect lasers from Earth.",
  "key_points": [
    "Astronauts brought back moon rocks and left mirrors on the surface that scientists still bounce lasers off today to measure the Earth-moon distance.",
    "Other countries like the Soviet Union independently tracked the Apollo spacecraft in real time and confirmed it reached the moon.",
    "Faking it would have needed total secrecy from thousands of engineers and foreign governments for over 50 years - nobody has ever leaked it."
  ],
  "recommendation": "Look up the laser-reflector experiments still running today - they're public, repeatable proof."
}}

If there isn't enough to go on for this specific claim, say plainly what would need to be
true for it to be real (e.g. "a law like this would be publicly announced by lawmakers"),
lean toward UNVERIFIED with lower confidence, and still avoid all banned phrases above."""

_FALLBACK = {
    "verdict": "UNVERIFIED",
    "confidence": 0,
    "explanation": "This claim couldn't be checked automatically right now.",
    "key_points": ["The automatic check didn't return a result this time.",
                   "Try a trusted fact-checking site or news source for this specific claim."],
    "recommendation": "Verify this claim with an authoritative source before sharing.",
}

_VALID_VERDICTS = {"TRUE", "FALSE", "MISLEADING", "UNVERIFIED"}


class GroqService:
    _instance: Optional["GroqService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "GroqService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._client = None
        return cls._instance

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set.")
        with self._lock:
            if self._client is None:
                from groq import Groq

                self._client = Groq(api_key=settings.groq_api_key)
                logger.info("Groq client initialized (model '%s').", settings.groq_model)
        return self._client

    # ------------------------------------------------------------------ #
    @staticmethod
    def _format_context(similar_claims: List[Dict]) -> str:
        if not similar_claims:
            return "(no sufficiently similar claims were found in the database)"
        lines = []
        for i, sc in enumerate(similar_claims, 1):
            lines.append(
                f"{i}. [{sc.get('verdict', 'UNVERIFIED')}] "
                f"(similarity {sc.get('similarity_score', 0):.2f}, "
                f"category {sc.get('category', 'Other')})\n"
                f"   \"{str(sc.get('claim_text', ''))[:300]}\""
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict]:
        text = (raw or "").strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        if not text.startswith("{"):
            brace = re.search(r"\{.*\}", text, re.DOTALL)
            if brace:
                text = brace.group(0)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    def generate_verdict(
        self,
        claim: str,
        similar_claims: List[Dict],
        web_context: Optional[str] = None,
    ) -> Dict:
        try:
            client = self._get_client()
            web_block = (
                f"\nLIVE WEB FACT-CHECKS FOUND FOR THIS CLAIM:\n{web_context}\n"
                if web_context else ""
            )
            prompt = _PROMPT_TEMPLATE.format(
                claim=claim,
                context=self._format_context(similar_claims),
                web_block=web_block,
            )
            resp = client.chat.completions.create(
                model=settings.groq_model,
                messages=[
                    {"role": "system",
                     "content": "You are a precise fact-checking assistant. "
                                "Always respond with a single valid JSON object."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content if resp.choices else ""
            data = self._parse_json(content)
            if not data:
                logger.warning("Groq returned unparseable output; using fallback.")
                return dict(_FALLBACK)
            return self._sanitize(data)
        except Exception as exc:  # noqa: BLE001
            logger.error("Groq call failed: %s", exc)
            return dict(_FALLBACK)

    @staticmethod
    def _sanitize(data: Dict) -> Dict:
        verdict = str(data.get("verdict", "UNVERIFIED")).upper().strip()
        if verdict not in _VALID_VERDICTS:
            verdict = "UNVERIFIED"
        try:
            confidence = int(round(float(data.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0
        confidence = max(0, min(100, confidence))
        key_points = data.get("key_points") or []
        if not isinstance(key_points, list):
            key_points = [str(key_points)]
        return {
            "verdict": verdict,
            "confidence": confidence,
            "explanation": str(data.get("explanation", "")).strip() or _FALLBACK["explanation"],
            "key_points": [str(k) for k in key_points][:6],
            "recommendation": str(data.get("recommendation", "")).strip()
            or _FALLBACK["recommendation"],
        }


def get_groq_service() -> GroqService:
    return GroqService()
