#!/usr/bin/env python
"""
audit_synthetic_claims.py
==========================

Quality/diversity/impact audit of the "synthetic" batch of claims added to
Pinecone outside the original data_consolidation.py pipeline.

That batch is actually TWO different populations, kept separate throughout
this audit rather than blended:
  - TRUE synthetic (LLM/template auto-generated): source_file
    'output_07_SYNTHETIC_202500_claims_45_categories.csv', ids 'syn_claim_*'.
    ~202,500 candidates.
  - Real-but-added (scraped datasets, not generated): MultiFC/GossipCop/PHEME
    ('mfc_*' / 'gc_*' / 'pheme_*'). ~56K candidates. Not audited for
    "coherence" here since they're real text, not model output.

Steps (see module functions): sample, quality-score via LLM judge + heuristics,
diversity, a 5-claim RAG impact comparison (full index vs original-only via a
Pinecone metadata filter), and a written report.

Usage:
    python scripts/audit_synthetic_claims.py
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import settings  # noqa: E402

MASTER_CSV = REPO_ROOT / "SOCIAL_MEDIA_FACTCHECK_MASTER_FINAL.csv"
SYNTHETIC_SOURCE_FILE = "output_07_SYNTHETIC_202500_claims_45_categories.csv"
ORIGINAL_SOURCE_FILES = [
    "FEVER_1_train_145449.csv",
    "MASTER_ALL_124756_claims_ALL_TOPICS_ALL_COUNTRIES.csv",
    "FACTSPAN_1_ALL_65090_claims_2007to2025.csv",
    "6_claimbuster_30270_claims.csv",
    "3_fakenewsnet_23196_claims.csv",
    "POLITIFACT_21152.csv",
]
CANONICAL_VERDICTS = {"TRUE", "FALSE", "MISLEADING", "UNVERIFIED"}
OUT_DIR = REPO_ROOT
SAMPLE_JSON = OUT_DIR / "audit_sample_synthetic.json"
REPORT_MD = OUT_DIR / "SYNTHETIC_QUALITY_AUDIT.md"

FETCH_BATCH = 100
RANDOM_SEED = 42


def get_index():
    from pinecone import Pinecone

    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_index_name)


def with_retry(fn, *args, attempts: int = 4, base_delay: float = 2.0, **kwargs):
    """Transient network blips (seen: Windows DNS getaddrinfo failures) shouldn't
    kill a long-running audit -- retry with exponential backoff before giving up."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts - 1:
                delay = base_delay * (2 ** attempt)
                print(f"    [retry] {type(exc).__name__}: {exc} -- waiting {delay:.0f}s "
                      f"(attempt {attempt+1}/{attempts})")
                time.sleep(delay)
    raise last_exc


def fetch_batch(index, ids: List[str]) -> Dict[str, dict]:
    out = {}
    for i in range(0, len(ids), FETCH_BATCH):
        batch = ids[i : i + FETCH_BATCH]
        res = with_retry(index.fetch, ids=batch, namespace=settings.pinecone_namespace)
        vecs = res.vectors if hasattr(res, "vectors") else res.get("vectors", {})
        for vid, v in vecs.items():
            md = v.metadata if hasattr(v, "metadata") else v.get("metadata", {})
            out[vid] = md or {}
    return out


# --------------------------------------------------------------------------- #
# Step 1: sample
# --------------------------------------------------------------------------- #
def sample_synthetic_claims(index, n: int = 100) -> List[dict]:
    import pandas as pd

    print(f"[1/5] Sampling {n} random synthetic (syn_claim_*) claims...")
    df = pd.read_csv(MASTER_CSV, low_memory=False)
    synth = df[df["source_file"] == SYNTHETIC_SOURCE_FILE]
    print(f"  local candidate pool: {len(synth):,} rows")

    random.seed(RANDOM_SEED)
    candidate_ids = synth["claim_id"].astype(str).tolist()
    random.shuffle(candidate_ids)

    confirmed: List[dict] = []
    idx_ptr = 0
    while len(confirmed) < n and idx_ptr < len(candidate_ids):
        chunk = candidate_ids[idx_ptr : idx_ptr + FETCH_BATCH]
        idx_ptr += FETCH_BATCH
        found = fetch_batch(index, chunk)
        for cid, md in found.items():
            if len(confirmed) >= n:
                break
            confirmed.append({
                "claim_id": cid,
                "claim_text": md.get("claim_text", ""),
                "verdict": md.get("verdict", ""),
                "category": md.get("category", ""),
                "topic": md.get("topic", ""),
                "confidence": md.get("confidence_score"),  # expect None -- see report
                "fact_checker_organization": md.get("fact_checker_organization", ""),
                "claim_severity_level": md.get("claim_severity_level", ""),
            })

    print(f"  confirmed present in Pinecone: {len(confirmed)}/{n} requested")
    SAMPLE_JSON.write_text(json.dumps(confirmed, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved -> {SAMPLE_JSON.relative_to(REPO_ROOT)}")
    return confirmed


# --------------------------------------------------------------------------- #
# Step 2: quality metrics
# --------------------------------------------------------------------------- #
def near_duplicate_pairs(claims: List[dict], threshold: float = 0.85) -> List[tuple]:
    texts = [c["claim_text"].lower().strip() for c in claims]
    pairs = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            ratio = SequenceMatcher(None, texts[i], texts[j]).ratio()
            if ratio >= threshold:
                pairs.append((i, j, round(ratio, 3)))
    return pairs


def llm_quality_scores(claims: List[dict]) -> List[dict]:
    """Batched LLM-judge quality scoring (1-5) with a one-line reason each."""
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    results = []
    batch_size = 10
    print(f"[2/5] Scoring quality via LLM judge ({len(claims)} claims, "
          f"batches of {batch_size})...")

    for i in range(0, len(claims), batch_size):
        batch = claims[i : i + batch_size]
        numbered = "\n".join(
            f'{j}. verdict={c["verdict"]!r} category={c["category"]!r} :: "{c["claim_text"]}"'
            for j, c in enumerate(batch)
        )
        prompt = (
            "You are auditing auto-generated fact-check training claims for quality. "
            "For EACH numbered claim below, rate its quality 1-5:\n"
            "5 = reads like a real claim a person might actually post, grammatically sound, plausible\n"
            "3 = understandable but awkward, generic, or template-like phrasing\n"
            "1 = incoherent, garbled, or leaks template artifacts (e.g. placeholder tokens, "
            "ref-id tags, broken grammar making the claim unclear)\n\n"
            f"{numbered}\n\n"
            'Respond with ONLY a JSON object: {"scores": [{"i": 0, "score": <1-5>, "reason": "<=12 words"}, ...]}'
        )
        try:
            resp = with_retry(
                client.chat.completions.create,
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1200,
                response_format={"type": "json_object"},
                attempts=3,
            )
            data = json.loads(resp.choices[0].message.content)
            scores = {int(s["i"]): s for s in data.get("scores", [])}
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] batch {i}-{i+batch_size} scoring failed: {exc}")
            scores = {}

        for j, c in enumerate(batch):
            s = scores.get(j, {})
            results.append({
                "claim_id": c["claim_id"],
                "score": s.get("score"),
                "reason": s.get("reason", ""),
            })
        print(f"  scored {min(i+batch_size, len(claims))}/{len(claims)}")
    return results


def quality_report(claims: List[dict], scores: List[dict], dup_pairs: List[tuple]) -> dict:
    verdict_counts = Counter(c["verdict"] for c in claims)
    invalid_verdicts = [c["verdict"] for c in claims if c["verdict"] not in CANONICAL_VERDICTS]
    score_vals = [s["score"] for s in scores if isinstance(s.get("score"), (int, float))]
    avg_score = round(sum(score_vals) / len(score_vals), 2) if score_vals else None
    low_quality = [s for s in scores if isinstance(s.get("score"), (int, float)) and s["score"] <= 2]

    return {
        "n_sampled": len(claims),
        "verdict_distribution": dict(verdict_counts),
        "invalid_verdicts_found": invalid_verdicts,
        "near_duplicate_pairs": len(dup_pairs),
        "near_duplicate_examples": [
            {"a": claims[i]["claim_text"], "b": claims[j]["claim_text"], "similarity": r}
            for i, j, r in dup_pairs[:5]
        ],
        "avg_llm_quality_score": avg_score,
        "low_quality_count": len(low_quality),
        "low_quality_examples": [
            {
                "claim_id": s["claim_id"],
                "score": s["score"],
                "reason": s["reason"],
                "text": next((c["claim_text"] for c in claims if c["claim_id"] == s["claim_id"]), ""),
            }
            for s in low_quality[:8]
        ],
    }


# --------------------------------------------------------------------------- #
# Step 3: diversity (full population, not just the sample)
# --------------------------------------------------------------------------- #
def diversity_report(sample: List[dict]) -> dict:
    import pandas as pd

    print("[3/5] Analyzing diversity (full synthetic population + sample cross-check)...")
    df = pd.read_csv(MASTER_CSV, low_memory=False)
    synth = df[df["source_file"] == SYNTHETIC_SOURCE_FILE]

    full_category = synth["category"].value_counts()
    full_topic = synth["topic"].value_counts()
    total = len(synth)

    over_represented = {
        k: round(v / total * 100, 1) for k, v in full_category.items() if v / total > 0.30
    }

    canonical_categories = {"Health", "Politics", "Science", "Technology", "Economy", "Other"}
    present_categories = set(full_category.index)
    missing = canonical_categories - present_categories

    sample_category = Counter(c["category"] for c in sample)

    return {
        "full_population_size": int(total),
        "unique_categories_full": int(synth["category"].nunique()),
        "unique_topics_full": int(synth["topic"].nunique()),
        "category_distribution_full_pct": {
            k: round(v / total * 100, 1) for k, v in full_category.items()
        },
        "over_represented_categories_gt30pct": over_represented,
        "canonical_categories_missing_entirely": sorted(missing),
        "top_10_topics_full": {k: int(v) for k, v in full_topic.head(10).items()},
        "sample_category_distribution": dict(sample_category),
    }


# --------------------------------------------------------------------------- #
# Step 4: RAG impact -- full index vs original-only
# --------------------------------------------------------------------------- #
TEST_CLAIMS = [
    "COVID-19 vaccines cause infertility in women",
    "Intermittent fasting completely eliminates the need for exercise to lose weight",
    "The government uses chemtrails to control the population",
    "Drinking celery juice cures autoimmune diseases",
    "5G towers were installed specifically to spread COVID-19",
]


def rag_compare(index, embedder, groq_service) -> List[dict]:
    """
    For each test claim, run the SAME real pipeline (embed once, then Groq
    reasons over whatever evidence was retrieved) under two retrieval scopes:
    the full index, and an original-only filter. This mirrors what a real
    user would actually see, not a retrieval-only proxy.
    """
    print(f"[4/5] RAG impact test: {len(TEST_CLAIMS)} claims x (full index vs original-only)...")
    results = []

    for claim in TEST_CLAIMS:
        print(f"  - {claim}")
        vector = embedder.encode_query(claim)

        full_res = with_retry(index.query, vector=vector, top_k=5, include_metadata=True,
                              namespace=settings.pinecone_namespace)
        orig_res = with_retry(index.query, vector=vector, top_k=5, include_metadata=True,
                              namespace=settings.pinecone_namespace,
                              filter={"source_file": {"$in": ORIGINAL_SOURCE_FILES}})

        def matches_to_list(res):
            ms = res.matches if hasattr(res, "matches") else res.get("matches", [])
            out = []
            for m in ms:
                md = (m.metadata if hasattr(m, "metadata") else m.get("metadata", {})) or {}
                score = m.score if hasattr(m, "score") else m.get("score")
                out.append({
                    "claim_text": md.get("claim_text", ""),
                    "verdict": md.get("verdict", "UNVERIFIED"),
                    "category": md.get("category", "Other"),
                    "source_file": md.get("source_file", ""),
                    "is_synthetic_or_added": md.get("source_file") not in ORIGINAL_SOURCE_FILES,
                    "similarity_score": round(float(score), 4) if score is not None else 0.0,
                })
            return out

        full_matches = matches_to_list(full_res)
        orig_matches = matches_to_list(orig_res)

        # Real end-to-end verdict generation (same service the API uses), one
        # call per condition -- this is what a user would actually be shown.
        full_llm = groq_service.generate_verdict(claim, full_matches)
        orig_llm = groq_service.generate_verdict(claim, orig_matches)

        added_matches = [m for m in full_matches if m["is_synthetic_or_added"]]

        results.append({
            "claim": claim,
            "full_index": {
                "verdict": full_llm["verdict"], "confidence": full_llm["confidence"],
                "explanation": full_llm["explanation"], "matches": full_matches,
            },
            "original_only": {
                "verdict": orig_llm["verdict"], "confidence": orig_llm["confidence"],
                "explanation": orig_llm["explanation"], "matches": orig_matches,
            },
            "synthetic_or_added_matches_in_full_result": added_matches,
            "verdict_changed": full_llm["verdict"] != orig_llm["verdict"],
            "top_match_changed": (
                (full_matches[0]["claim_text"] if full_matches else None)
                != (orig_matches[0]["claim_text"] if orig_matches else None)
            ),
        })

    return results


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    if not settings.pinecone_api_key or not settings.groq_api_key:
        print("[ERROR] PINECONE_API_KEY and GROQ_API_KEY must be set.")
        return 1
    if not MASTER_CSV.exists():
        print(f"[ERROR] {MASTER_CSV} not found.")
        return 1

    t0 = time.time()
    index = get_index()

    sample = sample_synthetic_claims(index, n=100)
    dup_pairs = near_duplicate_pairs(sample)
    scores = llm_quality_scores(sample)
    quality = quality_report(sample, scores, dup_pairs)

    diversity = diversity_report(sample)

    from services.embedding_service import get_embedding_service
    from services.groq_service import get_groq_service

    embedder = get_embedding_service()
    groq_service = get_groq_service()
    rag_results = rag_compare(index, embedder, groq_service)

    print("[5/5] Writing report...")
    write_report(quality, diversity, rag_results, sample)
    print(f"\nDone in {time.time()-t0:.0f}s. Report -> {REPORT_MD.relative_to(REPO_ROOT)}")
    return 0


def write_report(quality: dict, diversity: dict, rag_results: List[dict], sample: List[dict]) -> None:
    lines = []
    lines.append("# Synthetic Claims Quality Audit\n")
    lines.append(f"Sample size: {quality['n_sampled']} randomly-selected `syn_claim_*` "
                 f"claims out of {diversity['full_population_size']:,} total in that batch.\n")

    lines.append("## Quality\n")
    lines.append(f"- Verdict distribution in sample: {quality['verdict_distribution']}")
    lines.append(f"- Invalid/non-canonical verdicts found: {quality['invalid_verdicts_found'] or 'none'}")
    lines.append(f"- Average LLM-judge quality score (1-5): **{quality['avg_llm_quality_score']}**")
    lines.append(f"- Claims scored <=2/5: {quality['low_quality_count']}/{quality['n_sampled']}")
    lines.append(f"- Near-duplicate pairs (>=0.85 text similarity) in sample: {quality['near_duplicate_pairs']}")
    if quality["low_quality_examples"]:
        lines.append("\n**Low-quality examples:**")
        for ex in quality["low_quality_examples"]:
            lines.append(f"- ({ex['score']}/5) \"{ex['text']}\" — {ex['reason']}")

    lines.append("\n## Diversity\n")
    lines.append(f"- Unique categories (full population): {diversity['unique_categories_full']}")
    lines.append(f"- Unique topics (full population): {diversity['unique_topics_full']}")
    lines.append(f"- Over-represented categories (>30%): {diversity['over_represented_categories_gt30pct'] or 'none'}")
    lines.append(f"- Canonical app categories missing entirely: "
                 f"{diversity['canonical_categories_missing_entirely'] or 'none'}")
    lines.append(f"- Category distribution: {diversity['category_distribution_full_pct']}")

    lines.append("\n## RAG impact (full index vs original-only)\n")
    changed = sum(1 for r in rag_results if r["verdict_changed"])
    lines.append(f"- Verdict changed by including synthetic/added data: {changed}/{len(rag_results)} test claims\n")
    for r in rag_results:
        lines.append(f"### \"{r['claim']}\"")
        lines.append(f"- Full index: **{r['full_index']['verdict']}** ({r['full_index']['confidence']}%)")
        lines.append(f"- Original-only: **{r['original_only']['verdict']}** ({r['original_only']['confidence']}%)")
        lines.append(f"- Synthetic/added claims in top-5: {len(r['synthetic_or_added_matches_in_full_result'])}")
        for m in r["synthetic_or_added_matches_in_full_result"]:
            lines.append(f"  - [{m['similarity']}] ({m['verdict']}) \"{m['claim_text'][:100]}\"")
        lines.append("")

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    (OUT_DIR / "audit_rag_comparison.json").write_text(
        json.dumps(rag_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUT_DIR / "audit_diversity.json").write_text(
        json.dumps(diversity, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUT_DIR / "audit_quality.json").write_text(
        json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())
