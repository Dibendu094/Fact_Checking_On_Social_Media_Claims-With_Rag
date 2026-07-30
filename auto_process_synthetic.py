#!/usr/bin/env python
"""
auto_process_synthetic.py
=========================

Auto-process every CSV in a folder of synthetic fact-check exports:

    scan -> load -> normalize to the 21-column schema -> merge -> dedupe
    -> embed (multilingual-e5-large) -> upsert into Pinecone (fact-check-claims)

The vectors are added to the SAME index/namespace as the main dataset, so the
final report shows:   pre-existing total  +  newly uploaded  =  new index total.

Usage
-----
    python auto_process_synthetic.py --folder synthetic_files/
    python auto_process_synthetic.py --folder synthetic_files/ --dry-run
    python auto_process_synthetic.py --folder synthetic_files/ --no-upload

The Pinecone key is resolved from (in order): --pinecone-key, the PINECONE_API_KEY
environment variable, or backend/.env. It is never hardcoded in this file.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

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

try:
    from colorama import Fore, Style
    from colorama import init as _ci

    _ci()

    def c(t: str, col: str = "") -> str:
        return f"{col}{t}{Style.RESET_ALL}" if col else t

    CY, GR, YE, RE, BL = Fore.CYAN, Fore.GREEN, Fore.YELLOW, Fore.RED, Fore.BLUE
except ImportError:  # pragma: no cover
    def c(t: str, col: str = "") -> str:  # type: ignore
        return t

    CY = GR = YE = RE = BL = ""

# --------------------------------------------------------------------------- #
# Paths & constants
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
BACKEND_ENV = ROOT / "backend" / ".env"
LOG_DIR = ROOT / "backend" / "logs"
DEFAULT_FOLDER = ROOT / "synthetic_files"
MASTER_CSV = ROOT / "SOCIAL_MEDIA_FACTCHECK_MASTER_FINAL.csv"

DEFAULT_MODEL = "intfloat/multilingual-e5-large"
DEFAULT_INDEX = "fact-check-claims"
DEFAULT_NAMESPACE = "claims"

STANDARD_COLUMNS = [
    "claim_id", "claim_text", "verdict", "category", "confidence_score",
    "source_url", "evidence_url", "timestamp", "source_file", "claim_language",
    "fact_checker_organization", "claim_severity_level", "claim_date",
    "fact_check_date", "rationale", "topic", "misinformation_type",
    "platform_source", "audience_impact", "related_claim_ids",
    "verdict_rating_scale",
]

# Standard column -> candidate source names (checked as exact then substring).
COLUMN_KEYWORDS: Dict[str, List[str]] = {
    "claim_id": ["claim_id", "id"],
    "claim_text": ["claim_text", "claim", "statement", "content", "text", "post"],
    "verdict": ["verdict", "fact_label", "label", "rating", "status"],
    "category": ["category", "class"],
    "confidence_score": ["confidence_score", "confidence", "score", "probability"],
    "source_url": ["source_url", "url", "link"],
    "evidence_url": ["evidence_url", "evidence", "fact_check_url", "reference"],
    "timestamp": ["timestamp", "created_at"],
    "claim_language": ["claim_language", "language", "lang"],
    "fact_checker_organization": ["fact_checker_organization", "fact_checker",
                                  "organization", "publisher", "org"],
    "claim_severity_level": ["claim_severity_level", "severity", "severity_level"],
    "claim_date": ["claim_date"],
    "fact_check_date": ["fact_check_date", "checked_at", "check_date"],
    "rationale": ["rationale", "explanation", "reason", "justification"],
    "topic": ["topic", "subject"],
    "misinformation_type": ["misinformation_type", "misinfo_type", "type"],
    "platform_source": ["platform_source", "platform", "social_media"],
    "audience_impact": ["audience_impact", "impact", "reach"],
    "related_claim_ids": ["related_claim_ids", "related"],
    "verdict_rating_scale": ["verdict_rating_scale", "rating_scale", "scale"],
}

VERDICT_MAPPING = {
    "true": "TRUE", "real": "TRUE", "correct": "TRUE", "verified": "TRUE",
    "accurate": "TRUE", "supported": "TRUE", "legit": "TRUE", "fact": "TRUE",
    "false": "FALSE", "fake": "FALSE", "incorrect": "FALSE", "wrong": "FALSE",
    "debunked": "FALSE", "hoax": "FALSE", "misinformation": "FALSE",
    "pants on fire": "FALSE", "fabricated": "FALSE", "refuted": "FALSE",
    "misleading": "MISLEADING", "partly false": "MISLEADING",
    "partially false": "MISLEADING", "mixed": "MISLEADING",
    "half true": "MISLEADING", "mostly false": "MISLEADING",
    "mostly true": "MISLEADING", "exaggerated": "MISLEADING",
    "lacks context": "MISLEADING", "missing context": "MISLEADING",
    "unverified": "UNVERIFIED", "unknown": "UNVERIFIED",
    "unconfirmed": "UNVERIFIED", "disputed": "UNVERIFIED", "unclear": "UNVERIFIED",
}
CANONICAL_VERDICTS = {"TRUE", "FALSE", "MISLEADING", "UNVERIFIED"}

LOG = logging.getLogger("auto_process_synthetic")


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("auto_process_synthetic")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(LOG_DIR / "auto_process_synthetic.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(fh)
    return logger


def resolve_pinecone_key(cli_key: Optional[str]) -> Optional[str]:
    if cli_key:
        return cli_key
    if os.getenv("PINECONE_API_KEY"):
        return os.getenv("PINECONE_API_KEY")
    if BACKEND_ENV.exists():
        for line in BACKEND_ENV.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PINECONE_API_KEY="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return None


# --------------------------------------------------------------------------- #
# Normalization helpers
# --------------------------------------------------------------------------- #
def normalize_verdict(value) -> str:
    if pd.isna(value):
        return "UNVERIFIED"
    v = str(value).strip().lower()
    if not v:
        return "UNVERIFIED"
    if v in VERDICT_MAPPING:
        return VERDICT_MAPPING[v]
    up = v.upper()
    if up in CANONICAL_VERDICTS:
        return up
    for k, mapped in VERDICT_MAPPING.items():
        if k in v:
            return mapped
    return "UNVERIFIED"


def fix_confidence(value) -> float:
    try:
        s = float(value)
    except (TypeError, ValueError):
        return 0.70
    if pd.isna(s):
        return 0.70
    if 0.0 <= s <= 1.0:
        return s
    if s > 1.0:
        s = s / 100.0
        return s if 0.0 <= s <= 1.0 else 0.70
    return 0.70


def fuzzy_key(text: str, trim: int = 80) -> str:
    """lowercase, strip non-alphanumerics, collapse spaces, trim to `trim` chars.

    NOTE: the default 80 comes from the original spec, but it is aggressive for
    templated synthetic claims that share a long common prefix (e.g. "Viral
    rumor claims ..."). Use --fuzzy-trim 0 to compare full normalized text.
    """
    t = re.sub(r"[^a-z0-9\s]", "", str(text).lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t if trim <= 0 else t[:trim]


def map_columns(df: pd.DataFrame, filename: str) -> pd.DataFrame:
    lower_lookup = {col.lower().strip(): col for col in df.columns}
    used: set = set()
    out = pd.DataFrame(index=df.index)

    for std_col, keywords in COLUMN_KEYWORDS.items():
        chosen = None
        for kw in keywords:  # exact
            if kw in lower_lookup and lower_lookup[kw] not in used:
                chosen = lower_lookup[kw]
                break
        if chosen is None:  # substring
            for kw in keywords:
                for low, orig in lower_lookup.items():
                    if orig not in used and kw in low:
                        chosen = orig
                        break
                if chosen:
                    break
        out[std_col] = df[chosen] if chosen is not None else np.nan
        if chosen:
            used.add(chosen)

    out["source_file"] = filename
    return out


def apply_defaults(df: pd.DataFrame) -> pd.DataFrame:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # claim_id: generate where missing.
    df["claim_id"] = df["claim_id"].apply(
        lambda x: str(x) if pd.notna(x) and str(x).strip() else f"claim_{uuid.uuid4()}"
    )
    df["verdict"] = df["verdict"].apply(normalize_verdict)
    df["confidence_score"] = df["confidence_score"].apply(fix_confidence)
    df["timestamp"] = df["timestamp"].where(df["timestamp"].notna(), now)
    df["claim_language"] = df["claim_language"].where(df["claim_language"].notna(), "English")
    df["category"] = df["category"].where(df["category"].notna(), df["topic"])
    df["category"] = df["category"].where(df["category"].notna(), "Other")
    # Everything else -> empty string where missing (keeps CSV/Pinecone happy).
    for col in STANDARD_COLUMNS:
        if col not in df:
            df[col] = ""
        df[col] = df[col].where(df[col].notna(), "")
    return df[STANDARD_COLUMNS]


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def _has_claim_text_column(columns: List[str]) -> bool:
    """True if any column could map to claim_text (exact or substring)."""
    lows = [str(col).lower().strip() for col in columns]
    for kw in COLUMN_KEYWORDS["claim_text"]:
        if any(kw == low or kw in low for low in lows):
            return True
    return False


def load_and_normalize(folder: Path, sample: bool) -> pd.DataFrame:
    files = sorted(folder.glob("*.csv"))
    print(c(f"[SCANNING]    ", CY) + f"✓ Found {len(files)} CSV file(s) in {folder}")
    if not files:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    frames = []
    total_loaded = 0
    for f in files:
        # Cheap header peek: skip non-fact-check files (no claim/text column)
        # without loading them fully (e.g. mnist, california_housing samples).
        try:
            header_cols = list(pd.read_csv(f, nrows=0).columns)
        except Exception as exc:  # noqa: BLE001
            print(c(f"  [SKIP] {f.name}: unreadable header ({exc})", RE))
            continue
        if not _has_claim_text_column(header_cols):
            print(c(f"  [SKIP non-fact-check] {f.name} "
                    f"(no claim/text column: {header_cols[:6]})", YE))
            LOG.warning("Skipped non-fact-check file %s cols=%s", f.name, header_cols[:8])
            continue

        try:
            try:
                df = pd.read_csv(f, low_memory=False, on_bad_lines="skip")
            except UnicodeDecodeError:
                df = pd.read_csv(f, low_memory=False, on_bad_lines="skip", encoding="latin-1")
        except Exception as exc:  # noqa: BLE001
            print(c(f"  [SKIP] {f.name}: {exc}", RE))
            LOG.error("Skip %s: %s", f.name, exc)
            continue

        print(c(f"  • {f.name}", BL) + f"  shape={df.shape}  columns={list(df.columns)[:8]}")
        if sample and len(df):
            print(c(f"    sample: ", YE) + str(df.iloc[0].to_dict())[:160])
        mapped = map_columns(df, f.name)
        frames.append(mapped)
        total_loaded += len(df)

    if not frames:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    print(c(f"[LOADING]     ", CY) + f"✓ Loaded {total_loaded:,} claims")
    merged = pd.concat(frames, ignore_index=True)
    merged = apply_defaults(merged)
    print(c(f"[NORMALIZING] ", CY) + f"✓ {len(merged):,} normalized to 21 columns")
    print(c(f"[MERGING]     ", CY) + f"✓ Merged {len(merged):,} total")
    return merged


def deduplicate(df: pd.DataFrame, trim: int = 80) -> pd.DataFrame:
    before = len(df)
    # Clean: claim_text >= 10 chars.
    df["claim_text"] = df["claim_text"].astype(str).str.strip()
    df = df[df["claim_text"].str.len() >= 10]
    short_dropped = before - len(df)
    # Exact: same claim_id.
    df = df[~df["claim_id"].duplicated(keep="first")]
    after_id = len(df)
    # Fuzzy: normalized claim_text (trim configurable; see fuzzy_key docstring).
    df = df.assign(_fk=df["claim_text"].map(lambda t: fuzzy_key(t, trim)))
    df = df[~df["_fk"].duplicated(keep="first")].drop(columns="_fk")
    df = df.reset_index(drop=True)
    fuzzy_removed = after_id - len(df)
    removed = before - len(df)
    print(c(f"[DEDUPING]    ", CY)
          + f"✓ Removed {removed:,} duplicates → {len(df):,} unique"
          + f"  (short:{short_dropped:,} id:{before - short_dropped - after_id:,} "
            f"fuzzy@{trim or 'full'}:{fuzzy_removed:,})")
    return df


def validate(df: pd.DataFrame) -> None:
    checks = {
        "21 columns present": list(df.columns) == STANDARD_COLUMNS,
        "no null claim_id/text/verdict": not df[["claim_id", "claim_text", "verdict"]].isna().any().any(),
        "claim_text >= 10 chars": bool((df["claim_text"].str.len() >= 10).all()) if len(df) else True,
        "verdict in vocabulary": bool(df["verdict"].isin(CANONICAL_VERDICTS).all()) if len(df) else True,
        "confidence in [0,1]": bool(((df["confidence_score"] >= 0) & (df["confidence_score"] <= 1)).all()) if len(df) else True,
        "unique claim_ids": bool(df["claim_id"].is_unique),
    }
    print(c("\n[VALIDATION]", CY))
    for name, ok in checks.items():
        print(f"  {'✅' if ok else '❌'} {name}")


# --------------------------------------------------------------------------- #
# Embedding + Pinecone
# --------------------------------------------------------------------------- #
def get_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    device = "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            device = "cuda"
    except ImportError:
        pass
    print(c(f"[EMBEDDING]   ", CY) + f"loading {model_name} on {device} (first run ~2.3GB)…")
    return SentenceTransformer(model_name, device=device)


def build_metadata(row: pd.Series) -> dict:
    keep = ["claim_text", "verdict", "category", "topic", "platform_source",
            "claim_severity_level", "fact_checker_organization",
            "misinformation_type", "rationale", "source_file"]
    md = {}
    for k in keep:
        val = row.get(k, "")
        md[k] = str(val)[:1000] if val is not None else ""
    md["confidence_score"] = float(row.get("confidence_score", 0.70) or 0.70)
    return md


def embed_and_upload(df: pd.DataFrame, args, api_key: Optional[str]) -> Dict:
    result = {"pre_total": None, "uploaded": 0, "post_total": None, "vectors_saved_locally": 0}
    if df.empty:
        return result

    model = get_model(args.model)

    # --- Dry run: embed a small sample, no upload. --------------------------
    if args.dry_run:
        n = min(args.embed_batch, len(df))
        texts = [f"passage: {t[:512]}" for t in df["claim_text"].head(n)]
        vecs = model.encode(texts, batch_size=args.embed_batch,
                            normalize_embeddings=True, show_progress_bar=True)
        print(c(f"[DRY-RUN]     ", YE)
              + f"embedded {len(vecs)} sample rows, dim={len(vecs[0])}; no upload.")
        return result

    # --- Connect to Pinecone (unless --no-upload). --------------------------
    index = None
    if not args.no_upload:
        if not api_key:
            print(c("[UPLOAD] No Pinecone key — will save vectors locally instead.", YE))
            args.no_upload = True
        else:
            from pinecone import Pinecone

            index = Pinecone(api_key=api_key).Index(args.index)
            stats = index.describe_index_stats()
            ns = dict(stats.namespaces).get(args.namespace)
            result["pre_total"] = getattr(ns, "vector_count", 0) if ns else 0

    # --- Embed + upsert in batches. -----------------------------------------
    local_vectors = []
    total = len(df)
    start = time.time()
    uploaded = 0

    for i in tqdm(range(0, total, args.upsert_batch), desc="[UPLOADING]", unit="batch"):
        batch = df.iloc[i: i + args.upsert_batch]
        texts = [f"passage: {t[:512]}" for t in batch["claim_text"].astype(str)]

        embeddings = None
        for attempt in range(3):  # retry embedding up to 2x
            try:
                embeddings = model.encode(texts, batch_size=args.embed_batch,
                                          normalize_embeddings=True, show_progress_bar=False)
                break
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Embed batch %d attempt %d failed: %s", i, attempt + 1, exc)
                time.sleep(1)
        if embeddings is None:
            print(c(f"  [SKIP] embedding failed for batch {i}", RE))
            continue

        vectors = [
            {"id": str(row["claim_id"]), "values": emb.tolist(), "metadata": build_metadata(row)}
            for emb, (_, row) in zip(embeddings, batch.iterrows())
        ]

        if args.no_upload:
            local_vectors.extend(vectors)
            continue

        try:
            index.upsert(vectors=vectors, namespace=args.namespace)
            uploaded += len(vectors)
        except Exception as exc:  # noqa: BLE001
            LOG.error("Pinecone upsert failed at batch %d: %s", i, exc)
            print(c(f"  [WARN] upsert failed at batch {i}; saving remainder locally: {exc}", YE))
            local_vectors.extend(vectors)
            args.no_upload = True  # fall back to local for the rest

    # --- Local fallback save. -----------------------------------------------
    if local_vectors:
        import json

        out = ROOT / "pending_vectors.jsonl"
        with open(out, "w", encoding="utf-8") as fh:
            for v in local_vectors:
                fh.write(json.dumps(v) + "\n")
        result["vectors_saved_locally"] = len(local_vectors)
        print(c(f"[UPLOAD] Saved {len(local_vectors):,} vectors to {out.name} "
                f"(re-upload later).", YE))

    result["uploaded"] = uploaded
    if index is not None:
        try:
            stats = index.describe_index_stats()
            ns = dict(stats.namespaces).get(args.namespace)
            result["post_total"] = getattr(ns, "vector_count", None) if ns else None
        except Exception:  # noqa: BLE001
            pass
    LOG.info("Embed+upload done: uploaded=%d in %.1fs", uploaded, time.time() - start)
    return result


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def print_report(files_found, total_loaded, final_df, emb) -> None:
    dup_removed = total_loaded - len(final_df)
    print(c("\n" + "=" * 56, CY))
    print(c("📊 Processing Summary", CY))
    print(c("=" * 56, CY))
    print(f"  Files found:            {files_found}")
    print(f"  Total loaded:           {total_loaded:,} claims")
    print(f"  Duplicates removed:     {dup_removed:,}")
    print(f"  Final unique:           {len(final_df):,} claims")
    print(f"  Embeddings/uploaded:    {emb['uploaded']:,} vectors (1024 dims)")
    if emb.get("vectors_saved_locally"):
        print(f"  Saved locally (no net): {emb['vectors_saved_locally']:,} vectors")
    pre, post = emb.get("pre_total"), emb.get("post_total")
    if pre is not None:
        print(c("\n  ── Pinecone index (namespace 'claims') ──", CY))
        print(f"  Pre-existing total:     {pre:,}")
        print(f"  Newly uploaded:       + {emb['uploaded']:,}")
        if post is not None:
            print(f"  New index total:      = {post:,}")
        else:
            print(f"  Expected new total:   = {pre + emb['uploaded']:,}")
    print(c("=" * 56, CY))
    print(c("[COMPLETE]    ✓ All done!", GR))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Auto-process synthetic fact-check CSVs into Pinecone.")
    p.add_argument("--folder", default=str(DEFAULT_FOLDER))
    p.add_argument("--pinecone-key", default=None)
    p.add_argument("--index", default=DEFAULT_INDEX)
    p.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--embed-batch", type=int, default=32)
    p.add_argument("--upsert-batch", type=int, default=100)
    p.add_argument("--dry-run", action="store_true", help="Embed a sample; never upload.")
    p.add_argument("--process-only", action="store_true",
                   help="Stop after dedupe + master CSV (no embedding, no upload).")
    p.add_argument("--no-upload", action="store_true", help="Process + save vectors locally, skip Pinecone.")
    p.add_argument("--sample", action="store_true", help="Print a sample row from each file.")
    p.add_argument("--fuzzy-trim", type=int, default=80,
                   help="Chars of normalized claim_text used for fuzzy dedupe "
                        "(spec default 80; use 0 to compare full text).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    global LOG
    LOG = setup_logging()
    args = parse_args(argv)
    folder = Path(args.folder).expanduser().resolve()

    print(c("\n🚀 AUTO-PROCESS SYNTHETIC FACT-CHECK CSVs\n", CY))
    if not folder.exists():
        print(c(f"[ERROR] Folder not found: {folder}", RE))
        print(c(f"        Create it and add your output_XX_SYNTHETIC_*.csv files first.", YE))
        return 1

    files_found = len(sorted(folder.glob("*.csv")))
    merged = load_and_normalize(folder, sample=args.sample)
    total_loaded = len(merged)
    if merged.empty:
        print(c("[ERROR] No usable rows found. Nothing to do.", RE))
        return 1

    print(c("\n  Verdict distribution (pre-dedupe): ", CY)
          + str(merged["verdict"].value_counts().to_dict()))

    final_df = deduplicate(merged, trim=args.fuzzy_trim)
    validate(final_df)

    # Save master CSV.
    final_df.to_csv(MASTER_CSV, index=False, encoding="utf-8")
    print(c(f"\n[SAVE]        ", CY) + f"✓ Wrote {MASTER_CSV.name} ({len(final_df):,} rows × 21 cols)")

    if args.process_only:
        print(c("\n[PROCESS-ONLY] Skipping embedding/upload as requested.", YE))
        # Still surface the pre-existing index total for the pre+new = total math.
        pre = None
        key = resolve_pinecone_key(args.pinecone_key)
        if key:
            try:
                from pinecone import Pinecone
                st = Pinecone(api_key=key).Index(args.index).describe_index_stats()
                ns = dict(st.namespaces).get(args.namespace)
                pre = getattr(ns, "vector_count", 0) if ns else 0
            except Exception:  # noqa: BLE001
                pass
        emb = {"pre_total": pre, "uploaded": 0, "post_total": None}
        if pre is not None:
            print(c("\n  ── Pinecone math (namespace 'claims') ──", CY))
            print(f"  Pre-existing total:     {pre:,}")
            print(f"  New unique to upload:  +{len(final_df):,}")
            print(f"  Projected index total: ={pre + len(final_df):,}")
        print_report(files_found, total_loaded, final_df, emb)
        return 0

    api_key = resolve_pinecone_key(args.pinecone_key)
    emb = embed_and_upload(final_df, args, api_key)
    print_report(files_found, total_loaded, final_df, emb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
