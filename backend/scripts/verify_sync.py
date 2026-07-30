#!/usr/bin/env python
"""
verify_sync.py
===============

Check whether the local dataset (claims_clean.csv, backs verdict/category
distributions in /api/stats) is behind the live Pinecone index (the true
database size, backs total_claims). Exits non-zero on drift so it can gate a
deploy step or be run on a schedule (cron / Windows Task Scheduler) — this
repo has no git remote / CI yet, so there is no GitHub Actions workflow to
hook this into; run it manually or via a local scheduler instead.

Usage:
    python backend/scripts/verify_sync.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Unicode-safe stdout on Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import settings  # noqa: E402


def main() -> int:
    import pandas as pd
    from pinecone import Pinecone

    if not settings.pinecone_api_key:
        print("[ERROR] PINECONE_API_KEY not set.")
        return 2

    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index_name)
    stats = index.describe_index_stats()
    pinecone_count = getattr(stats, "total_vector_count", None)
    if pinecone_count is None and isinstance(stats, dict):
        pinecone_count = stats.get("total_vector_count", 0)

    csv_path = settings.processed_csv
    csv_count = 0
    if csv_path.exists():
        csv_count = len(pd.read_csv(csv_path, usecols=["claim_id"], low_memory=False))

    diff = pinecone_count - csv_count
    print(f"Pinecone (live index, true DB size): {pinecone_count:,}")
    print(f"Local CSV (backs verdict/category stats): {csv_count:,}")

    if diff == 0:
        print("SYNC OK — local dataset matches the live index.")
        return 0

    print(f"OUT OF SYNC — Pinecone has {diff:,} more claims than the local CSV.")
    print("These extra claims are searchable (RAG uses Pinecone directly) but")
    print("won't appear in /api/stats verdict_distribution/category_distribution.")
    print("Run auto_process_synthetic.py against the source file(s) that were")
    print("uploaded, then data_consolidation.py, to fold them into claims_clean.csv.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
