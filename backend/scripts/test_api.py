#!/usr/bin/env python
"""
test_api.py
===========

Exercise the running Fact-Check API against a set of sample claims.

    python scripts/test_api.py --health-check     # deps only, no LLM calls
    python scripts/test_api.py                    # run all 10 sample claims
    python scripts/test_api.py --claim "..."      # one custom claim
    python scripts/test_api.py --limit 3          # first N samples

The API must already be running (uvicorn on :8000). Note that the FIRST check
loads the ~2.3 GB embedding model into memory and can take a minute; later
checks are much faster.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

DEFAULT_BASE = "http://localhost:8000"

SAMPLE_CLAIMS = [
    "COVID-19 vaccines contain microchips",
    "The Earth is flat",
    "Water boils at 100 degrees Celsius",
    "Elon Musk bought Twitter for $44 billion",
    "Vitamin C cures cancer",
    "Climate change is real",
    "5G causes COVID-19",
    "Vaccines cause autism",
    "The moon landing was faked",
    "India won the cricket world cup in 2023",
]

TIER_LABEL = {
    "HIGH": "HIGH    ", "MEDIUM": "MEDIUM  ",
    "LOW": "LOW     ", "VERY_LOW": "VERY_LOW",
}


def health_check(base: str) -> int:
    print(f"\n── Health check: {base}/health ──")
    try:
        r = httpx.get(f"{base}/health", timeout=20)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Could not reach the API: {exc}")
        print("   Start it with:  python -m uvicorn main:app --reload --port 8000")
        return 1

    d = r.json()
    rows = [
        ("status", d.get("status")),
        ("version", d.get("version")),
        ("pinecone_connected", d.get("pinecone_connected")),
        ("vector_count", f"{d.get('vector_count'):,}" if d.get("vector_count") else "—"),
        ("llm_configured", d.get("llm_configured")),
        ("web_search_active", d.get("web_search_active")),
        ("embedding_model_loaded", d.get("embedding_model_loaded")),
    ]
    for k, v in rows:
        mark = "✅" if v not in (False, None, "—") else "⚠️ "
        print(f"  {mark} {k:24} {v}")
    return 0 if d.get("status") in ("healthy", "degraded") else 1


def run_claim(base: str, claim: str, timeout: float) -> None:
    t0 = time.time()
    try:
        r = httpx.post(f"{base}/api/fact-check", json={"claim": claim}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ {claim[:48]:50} request failed: {exc}")
        return
    wall = (time.time() - t0) * 1000

    if r.status_code != 200:
        detail = ""
        try:
            detail = str(r.json().get("detail", ""))[:60]
        except Exception:  # noqa: BLE001
            pass
        print(f"  ❌ {claim[:48]:50} HTTP {r.status_code} {detail}")
        return

    d = r.json()
    tier = TIER_LABEL.get(d.get("confidence_tier", ""), d.get("confidence_tier", "?"))
    srcs = len(d.get("sources") or [])
    print(f"  {d['verdict']:<11} {d['confidence']:>3}%  tier={tier} "
          f"web={str(d.get('web_search_used')):<5} src={srcs}  "
          f"{int(d.get('processing_time_ms', wall)):>6}ms  {claim[:42]}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Test the Fact-Check API.")
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--health-check", action="store_true")
    p.add_argument("--claim", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--timeout", type=float, default=180.0)
    args = p.parse_args(argv)

    rc = health_check(args.base)
    if args.health_check or rc != 0:
        return rc

    claims = [args.claim] if args.claim else SAMPLE_CLAIMS[: args.limit]
    print(f"\n── Fact-checking {len(claims)} claim(s) ──")
    print("  (the first call loads the embedding model; allow ~1 minute)\n")
    print(f"  {'VERDICT':<11} {'CONF':>4}  {'TIER':<13} {'WEB':<10} {'SRC':<5} "
          f"{'TIME':>8}  CLAIM")
    print("  " + "-" * 100)

    started = time.time()
    for claim in claims:
        run_claim(args.base, claim, args.timeout)
    print(f"\n  Done in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
