#!/usr/bin/env python
"""
sync_pinecone_to_csv.py
========================

Fold Pinecone vectors that aren't yet in claims_clean.csv back into it, so
/api/stats' verdict/category distributions cover the full index, not just
the originally-consolidated subset.

Two ways to find the missing claims, cheapest first:

1. --from-file PATH  (fast, no Pinecone pagination): check which rows of an
   existing CSV (e.g. a prior auto_process_synthetic.py output) are already
   present as vector IDs in Pinecone, and treat matches as "already indexed,
   just missing locally." Use this whenever you know what was uploaded — a
   handful of `index.fetch()` batches, not a full index crawl.

2. --full-export     (slow, real pagination): enumerate every vector ID in
   the index via Pinecone's list() API and fetch() each batch's metadata.
   Correct (unlike a "query with a zero vector" trick, which is not a
   reliable way to enumerate an index and can silently miss or duplicate
   vectors) but touches the whole index — expect one API call per ~100 IDs,
   so a 484K-vector index is several thousand calls. Only use this when you
   don't have a candidate source file, or want to double-check for vectors
   no local file accounts for.

In both modes, only vectors CONFIRMED present in Pinecone are added — this
script never assumes a local file's rows all actually made it into the index.

Usage:
    python scripts/sync_pinecone_to_csv.py --from-file ../SOCIAL_MEDIA_FACTCHECK_MASTER_FINAL.csv
    python scripts/sync_pinecone_to_csv.py --full-export
    python scripts/sync_pinecone_to_csv.py --from-file X.csv --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set

# Unicode-safe stdout on Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    def tqdm(it=None, **_k):  # type: ignore
        return it if it is not None else []

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import settings  # noqa: E402

FINAL_COLUMNS = [
    "claim_id", "claim_text", "verdict", "category", "confidence_score",
    "source_url", "evidence_url", "timestamp", "source_file",
]
FETCH_BATCH = 100  # keeps the GET request URI under Pinecone's length limit


def get_index():
    from pinecone import Pinecone

    if not settings.pinecone_api_key:
        raise SystemExit("PINECONE_API_KEY is not set.")
    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_index_name)


def confirmed_ids_from_file(index, path: Path) -> Set[str]:
    """Which claim_ids in this CSV actually exist in Pinecone (verified, not assumed)."""
    import pandas as pd

    df = pd.read_csv(path, low_memory=False, usecols=["claim_id"])
    candidate_ids = df["claim_id"].astype(str).tolist()
    print(f"Checking {len(candidate_ids):,} candidate ids from {path.name} against Pinecone...")

    confirmed: Set[str] = set()
    for i in tqdm(range(0, len(candidate_ids), FETCH_BATCH), desc="Verifying", unit="batch"):
        batch = candidate_ids[i:i + FETCH_BATCH]
        res = index.fetch(ids=batch, namespace=settings.pinecone_namespace)
        vecs = res.vectors if hasattr(res, "vectors") else res.get("vectors", {})
        confirmed.update(vecs.keys())
    print(f"Confirmed {len(confirmed):,}/{len(candidate_ids):,} ids are actually in Pinecone.")
    return confirmed


def all_ids_full_export(index) -> Iterable[str]:
    """Enumerate every vector id in the namespace via Pinecone's real pagination API."""
    for page in index.list(namespace=settings.pinecone_namespace):
        vectors = page.vectors if hasattr(page, "vectors") else page.get("vectors", [])
        for item in vectors:
            yield item.id if hasattr(item, "id") else item


def fetch_metadata(index, ids: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for i in tqdm(range(0, len(ids), FETCH_BATCH), desc="Fetching metadata", unit="batch"):
        batch = ids[i:i + FETCH_BATCH]
        res = index.fetch(ids=batch, namespace=settings.pinecone_namespace)
        vecs = res.vectors if hasattr(res, "vectors") else res.get("vectors", {})
        for vid, v in vecs.items():
            md = v.metadata if hasattr(v, "metadata") else v.get("metadata", {})
            out[vid] = md or {}
    return out


def metadata_to_row(claim_id: str, md: dict) -> dict:
    return {
        "claim_id": claim_id,
        "claim_text": md.get("claim_text", ""),
        "verdict": md.get("verdict", "UNVERIFIED"),
        "category": md.get("category", "Other"),
        "confidence_score": md.get("confidence_score", 0.5),
        "source_url": md.get("source_url", "N/A"),
        "evidence_url": md.get("evidence_url", "N/A"),
        "timestamp": md.get("timestamp", ""),
        "source_file": md.get("source_file", "pinecone_sync"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from-file", type=str, default=None,
                   help="CSV of candidate claims to verify against Pinecone (fast path).")
    p.add_argument("--full-export", action="store_true",
                   help="Enumerate the entire index via list()+fetch() (slow path).")
    p.add_argument("--dry-run", action="store_true", help="Report what would change; don't write.")
    args = p.parse_args()

    if not args.from_file and not args.full_export:
        p.error("pass --from-file PATH or --full-export")

    import pandas as pd

    index = get_index()
    csv_path = settings.processed_csv
    existing = pd.read_csv(csv_path, low_memory=False) if csv_path.exists() else pd.DataFrame(columns=FINAL_COLUMNS)
    existing_ids = set(existing["claim_id"].astype(str)) if len(existing) else set()
    print(f"Local claims_clean.csv currently has {len(existing):,} rows.")

    if args.from_file:
        confirmed = confirmed_ids_from_file(index, Path(args.from_file))
        new_ids = sorted(confirmed - existing_ids)
    else:
        print("Enumerating the full index (this can take a while for large indexes)...")
        all_ids = list(tqdm(all_ids_full_export(index), desc="Listing ids", unit="id"))
        print(f"Index has {len(all_ids):,} total vector ids.")
        new_ids = sorted(set(all_ids) - existing_ids)

    print(f"{len(new_ids):,} ids are in Pinecone but not in claims_clean.csv.")
    if not new_ids:
        print("Nothing to add. Already in sync.")
        return 0

    if args.dry_run:
        print(f"[DRY-RUN] Would add {len(new_ids):,} rows. Sample ids: {new_ids[:5]}")
        return 0

    metadata = fetch_metadata(index, new_ids)
    new_rows = [metadata_to_row(cid, metadata.get(cid, {})) for cid in new_ids]
    new_df = pd.DataFrame(new_rows)[FINAL_COLUMNS]

    merged = pd.concat([existing[FINAL_COLUMNS], new_df], ignore_index=True)
    merged = merged.drop_duplicates(subset=["claim_id"], keep="first")

    backup = csv_path.with_suffix(".csv.backup")
    if csv_path.exists() and not backup.exists():
        import shutil

        shutil.copy(csv_path, backup)
        print(f"Backed up original to {backup.name}")

    merged.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"Wrote {len(merged):,} total rows to {csv_path} (+{len(new_df):,} new).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
