# Pinecone ↔ CSV Sync Guide

## The problem

- **Pinecone** (the vector index actually used for RAG retrieval): **484,848** claims.
- **`backend/data/processed/claims_clean.csv`** (backs `/api/stats`' verdict/category
  breakdowns): **259,648** claims.
- The gap (**225,200**) comes from a synthetic batch that was embedded and uploaded to
  Pinecone directly from a separate Colab/GPU run, and never folded back into the CSV.

Fact-checking itself was never affected — the RAG pipeline queries Pinecone directly, so
it always searched the full 484,848. Only the **stats endpoint** was blind to the gap.

## What's fixed

### Phase 1 — `/api/stats` now tells the truth (done)

`total_claims` is now the live Pinecone count (`describe_index_stats()`,
`services/pinecone_service.index_stats()`), fetched fresh on every call — it's cheap
(one lightweight API call) and this is exactly the field where staleness matters most.

`verdict_distribution`, `category_distribution`, and `accuracy_rate` still come from the
local CSV — call that out explicitly rather than fabricate a breakdown for claims we
don't have local labels for. A new `claims_indexed_locally` field makes that basis
explicit.

```bash
curl http://localhost:8000/api/stats
# {"total_claims": 484848, "claims_indexed_locally": 259648, ...}
```

The frontend's About page (`frontend/src/pages/About.jsx`) now fetches this live instead
of hardcoding "484,848" in copy, so it can't go stale again as the index grows. (Nothing
else in the current frontend calls `/api/stats` — the Dashboard page shows a signed-in
user's own history from Supabase, a separate, correctly-scoped number.)

### Phase 2 — folding the missing claims back into the CSV (script ready, not auto-run)

`backend/scripts/sync_pinecone_to_csv.py` — two modes:

```bash
# Fast path: verify a known source file's ids actually exist in Pinecone, add
# the confirmed ones. Use this when you know what was uploaded.
python scripts/sync_pinecone_to_csv.py --from-file ../SOCIAL_MEDIA_FACTCHECK_MASTER_FINAL.csv --dry-run
python scripts/sync_pinecone_to_csv.py --from-file ../SOCIAL_MEDIA_FACTCHECK_MASTER_FINAL.csv

# Slow path: no candidate file — enumerate the whole index for real via
# Pinecone's list() + fetch() pagination (NOT a "query with a zero vector"
# trick, which does not reliably enumerate an index).
python scripts/sync_pinecone_to_csv.py --full-export
```

Either way, a row is only added if its `claim_id` is **confirmed present in Pinecone** —
never assumed from a local file alone. Backs up `claims_clean.csv` before writing.

> `SOCIAL_MEDIA_FACTCHECK_MASTER_FINAL.csv` at the repo root (from an earlier
> `auto_process_synthetic.py` run) was spot-checked and its `claim_id`s **are** present in
> Pinecone, but its row count (258,606) doesn't cleanly match the 225,200 gap — some rows
> likely weren't part of the actual upload, or the upload used a filtered subset. Run the
> `--from-file` command above to reconcile exactly rather than assume.

### Phase 3 — catching future drift (local script, not CI)

**This project has no git remote and no CI/CD configured** (`git status` reports "not a
git repository"), so GitHub Actions workflows would be inert — nothing to trigger them.
Instead: `backend/scripts/verify_sync.py`, a plain script you can run by hand or wire
into a local scheduler (cron, Windows Task Scheduler) before a deploy:

```bash
python backend/scripts/verify_sync.py
# exit 0 = synced, exit 1 = drift detected (prints the gap and what to run)
```

If you later `git init` and push to GitHub, wrap this same script in a workflow step —
the script itself doesn't need to change.

## Rule going forward

Never upload claims to Pinecone without also running them through
`data_consolidation.py` into `claims_clean.csv` (or use `auto_process_synthetic.py`,
which does both in one pass and only uploads to Pinecone after building the CSV rows).
