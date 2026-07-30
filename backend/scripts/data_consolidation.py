#!/usr/bin/env python
"""
data_consolidation.py
=====================

Consolidate every raw fact-check dataset found in ``backend/data/raw/`` into a
single, clean, standardized dataset ready for embedding + Pinecone upload.

The script is intentionally *file-count agnostic*: it scans the raw directory
and processes whatever CSV / JSON / JSONL / TSV / XLSX files are present. Column
names are auto-mapped to a fixed 9-column schema, verdicts and categories are
normalized to a closed vocabulary, duplicates are removed, and stable claim IDs
are generated.

Usage
-----
    python backend/scripts/data_consolidation.py
    python backend/scripts/data_consolidation.py --dry-run
    python backend/scripts/data_consolidation.py --input-dir path/to/raw

Outputs
-------
    backend/data/processed/claims_clean.csv
    backend/data/processed/claims_clean.json
    backend/data/processed/consolidation_report.txt
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Ensure Unicode (arrows, emojis) print correctly on Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

# --------------------------------------------------------------------------- #
# Optional pretty deps (degrade gracefully if missing)
# --------------------------------------------------------------------------- #
try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    def tqdm(iterable=None, **_kwargs):  # type: ignore
        return iterable if iterable is not None else []

try:
    from colorama import Fore, Style
    from colorama import init as _colorama_init

    _colorama_init()

    def c(text: str, color: str = "") -> str:
        return f"{color}{text}{Style.RESET_ALL}" if color else text

    CY, GR, YE, RE, MA, BL = (
        Fore.CYAN,
        Fore.GREEN,
        Fore.YELLOW,
        Fore.RED,
        Fore.MAGENTA,
        Fore.BLUE,
    )
except ImportError:  # pragma: no cover
    def c(text: str, color: str = "") -> str:  # type: ignore
        return text

    CY = GR = YE = RE = MA = BL = ""


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DEFAULT_RAW_DIR = BACKEND_DIR / "data" / "raw"
PROCESSED_DIR = BACKEND_DIR / "data" / "processed"
LOG_DIR = BACKEND_DIR / "logs"

CSV_OUT = PROCESSED_DIR / "claims_clean.csv"
JSON_OUT = PROCESSED_DIR / "claims_clean.json"
REPORT_OUT = PROCESSED_DIR / "consolidation_report.txt"
LOG_FILE = LOG_DIR / "consolidation.log"

TODAY = date.today().strftime("%Y-%m-%d")

# --------------------------------------------------------------------------- #
# Schema definitions
# --------------------------------------------------------------------------- #
FINAL_COLUMNS = [
    "claim_id",
    "claim_text",
    "verdict",
    "category",
    "confidence_score",
    "source_url",
    "evidence_url",
    "timestamp",
    "source_file",
]

# Standard column -> keywords used to detect the original column name.
# Longer / more specific keywords are listed first so they win ties.
COLUMN_KEYWORDS: Dict[str, List[str]] = {
    "claim_text": [
        "claim", "statement", "headline", "description", "content",
        "tweet", "post", "title", "text",
    ],
    "verdict": [
        "fact_check", "classification", "verdict", "label", "status",
        "result", "rating", "outcome",
    ],
    "category": [
        "category", "topic", "domain", "subject", "type", "tag", "class",
    ],
    "source_url": [
        "source_url", "tweet_url", "post_url", "original_link", "source",
        "link", "url",
    ],
    "evidence_url": [
        "fact_check_url", "evidence", "reference", "debunk_url",
        "article_url", "proof",
    ],
    "timestamp": [
        "created_at", "published_at", "checked_at", "timestamp", "date",
        "time",
    ],
    "confidence_score": [
        "confidence", "probability", "certainty", "accuracy", "score",
        "weight",
    ],
}

DEFAULTS = {
    "verdict": "UNVERIFIED",
    "category": "Other",
    "source_url": "N/A",
    "evidence_url": "N/A",
    "timestamp": TODAY,
    "confidence_score": 0.5,
}

# --------------------------------------------------------------------------- #
# Verdict / category normalization maps
# --------------------------------------------------------------------------- #
VERDICT_MAPPING = {
    # TRUE
    "true": "TRUE", "real": "TRUE", "correct": "TRUE", "verified": "TRUE",
    "accurate": "TRUE", "supported": "TRUE", "legit": "TRUE",
    "legitimate": "TRUE", "fact": "TRUE",
    # FALSE
    "false": "FALSE", "fake": "FALSE", "incorrect": "FALSE", "wrong": "FALSE",
    "debunked": "FALSE", "hoax": "FALSE", "fake news": "FALSE",
    "misinformation": "FALSE", "lie": "FALSE", "pants on fire": "FALSE",
    "fabricated": "FALSE",
    # MISLEADING
    "misleading": "MISLEADING", "partly false": "MISLEADING",
    "partially false": "MISLEADING", "mixed": "MISLEADING",
    "half true": "MISLEADING", "mostly false": "MISLEADING",
    "mostly true": "MISLEADING", "exaggerated": "MISLEADING",
    "lacks context": "MISLEADING", "missing context": "MISLEADING",
    "distorted": "MISLEADING", "manipulated": "MISLEADING",
    # UNVERIFIED
    "unverified": "UNVERIFIED", "unknown": "UNVERIFIED",
    "unconfirmed": "UNVERIFIED", "disputed": "UNVERIFIED",
    "unclear": "UNVERIFIED", "needs context": "UNVERIFIED",
}

# Extra real-world aliases (dataset-specific labels) folded into the 4 classes.
# These extend the spec mapping so messy source labels normalize sensibly
# instead of all collapsing to UNVERIFIED.
VERDICT_ALIASES = {
    "supports": "TRUE", "t": "TRUE", "mostly-true": "MISLEADING",
    "refutes": "FALSE", "refuted": "FALSE", "f": "FALSE", "pants-fire": "FALSE",
    "barely-true": "MISLEADING", "half-true": "MISLEADING",
    "half-flip": "MISLEADING", "not enough info": "UNVERIFIED",
    "notenoughinfo": "UNVERIFIED", "nei": "UNVERIFIED",
    "not enough information": "UNVERIFIED", "conflicting": "MISLEADING",
    "cherry picking": "MISLEADING", "cherry-picking": "MISLEADING",
    "full-flop": "MISLEADING", "no-flip": "TRUE", "pants-on-fire": "FALSE",
}
VERDICT_MAPPING = {**VERDICT_ALIASES, **VERDICT_MAPPING}

CANONICAL_VERDICTS = {"TRUE", "FALSE", "MISLEADING", "UNVERIFIED"}

CATEGORY_MAPPING = {
    # Health
    "health": "Health", "medical": "Health", "medicine": "Health",
    "covid": "Health", "vaccine": "Health", "disease": "Health",
    "coronavirus": "Health", "virus": "Health",
    # Politics
    "politics": "Politics", "political": "Politics", "government": "Politics",
    "election": "Politics", "policy": "Politics", "law": "Politics",
    # Science
    "science": "Science", "scientific": "Science", "environment": "Science",
    "climate": "Science", "space": "Science",
    # Technology
    "technology": "Technology", "tech": "Technology", "ai": "Technology",
    "internet": "Technology", "social media": "Technology",
    "cyber": "Technology",
    # Economy
    "economy": "Economy", "finance": "Economy", "business": "Economy",
    "money": "Economy", "tax": "Economy",
}
CANONICAL_CATEGORIES = {
    "Health", "Politics", "Science", "Technology", "Economy", "Other",
}

SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".xls"}


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("data_consolidation")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    )
    logger.addHandler(fh)
    return logger


LOG = logging.getLogger("data_consolidation")


# --------------------------------------------------------------------------- #
# File loading
# --------------------------------------------------------------------------- #
def _read_with_encoding_fallback(reader, path: Path, **kwargs) -> pd.DataFrame:
    """Try utf-8 first, fall back to latin-1 for encoding-sensitive readers."""
    try:
        return reader(path, encoding="utf-8", **kwargs)
    except (UnicodeDecodeError, UnicodeError):
        LOG.warning("utf-8 failed for %s, retrying with latin-1", path.name)
        return reader(path, encoding="latin-1", **kwargs)


def load_file(path: Path) -> Optional[pd.DataFrame]:
    """Load a single raw file into a DataFrame based on its extension."""
    ext = path.suffix.lower()
    try:
        if ext == ".csv":
            df = _read_with_encoding_fallback(
                pd.read_csv, path, on_bad_lines="skip", low_memory=False
            )
        elif ext == ".tsv":
            df = _read_with_encoding_fallback(
                pd.read_csv, path, sep="\t", on_bad_lines="skip",
                low_memory=False,
            )
        elif ext == ".jsonl":
            df = _read_with_encoding_fallback(
                pd.read_json, path, lines=True
            )
        elif ext == ".json":
            try:
                df = _read_with_encoding_fallback(pd.read_json, path)
            except ValueError:
                # Some ".json" files are actually line-delimited.
                df = _read_with_encoding_fallback(pd.read_json, path, lines=True)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(path)  # openpyxl handles encoding internally
        else:
            LOG.warning("Unsupported extension, skipping: %s", path.name)
            return None
    except Exception as exc:  # noqa: BLE001 - report and continue
        LOG.error("Failed to load %s: %s", path.name, exc)
        print(c(f"  [SKIP] Could not load {path.name}: {exc}", RE))
        return None

    return df


def discover_files(raw_dir: Path) -> List[Path]:
    files = sorted(
        p for p in raw_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return files


# --------------------------------------------------------------------------- #
# Column mapping
# --------------------------------------------------------------------------- #
def map_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    """
    Detect original columns and rename them to the standard schema.

    Returns a new DataFrame containing exactly the 7 mapped source columns
    (unmatched ones are created as NaN) plus a mapping report.
    """
    lower_lookup = {col.lower().strip(): col for col in df.columns}
    used_original: set = set()
    mapping: Dict[str, Optional[str]] = {}

    for std_col, keywords in COLUMN_KEYWORDS.items():
        chosen: Optional[str] = None

        # Pass 1: exact (case-insensitive) match on a keyword.
        for kw in keywords:
            if kw in lower_lookup and lower_lookup[kw] not in used_original:
                chosen = lower_lookup[kw]
                break

        # Pass 2: substring / keyword-contained-in-column-name match.
        if chosen is None:
            for kw in keywords:
                for low, original in lower_lookup.items():
                    if original in used_original:
                        continue
                    if kw in low:
                        chosen = original
                        break
                if chosen:
                    break

        mapping[std_col] = chosen
        if chosen:
            used_original.add(chosen)

    # Build a clean frame with the 7 standard source columns.
    out = pd.DataFrame(index=df.index)
    for std_col in COLUMN_KEYWORDS:
        src = mapping[std_col]
        out[std_col] = df[src] if src is not None else np.nan

    return out, mapping


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
    # Keyword containment fallback (e.g. "mostly false claim").
    for key, mapped in VERDICT_MAPPING.items():
        if key in v:
            return mapped
    return "UNVERIFIED"


def normalize_category(value) -> str:
    if pd.isna(value):
        return "Other"
    cat = str(value).strip().lower()
    if not cat:
        return "Other"
    if cat in CATEGORY_MAPPING:
        return CATEGORY_MAPPING[cat]
    for key, mapped in CATEGORY_MAPPING.items():
        if key in cat:
            return mapped
    return "Other"


def fix_confidence(value) -> Tuple[float, bool]:
    """Return (clean_score, was_fixed)."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.5, True
    if pd.isna(score):
        return 0.5, True
    if 0.0 <= score <= 1.0:
        return score, False
    if score > 1.0:
        score = score / 100.0
        if 0.0 <= score <= 1.0:
            return score, True
    return 0.5, True


# --------------------------------------------------------------------------- #
# Report formatting
# --------------------------------------------------------------------------- #
VERDICT_ICONS = {
    "TRUE": "✅ TRUE", "FALSE": "❌ FALSE",
    "MISLEADING": "⚠️  MISLEADING", "UNVERIFIED": "❓ UNVERIFIED",
}
CATEGORY_ICONS = {
    "Health": "🏥 Health", "Politics": "🏛️  Politics", "Science": "🔬 Science",
    "Technology": "💻 Technology", "Economy": "💰 Economy", "Other": "📌 Other",
}


def build_report(stats: dict) -> str:
    line = "  " + "─" * 53
    L: List[str] = []
    L.append("=" * 60)
    L.append("          FACT-CHECKER DATA CONSOLIDATION REPORT")
    L.append("=" * 60)
    L.append("")
    L.append("FILES PROCESSED:")
    for i, (name, rows) in enumerate(stats["files"], start=1):
        L.append(f"  File {i}: {name:<34} → {rows:>9,} rows")
    L.append(line)
    L.append(f"  {'TOTAL LOADED:':<36} → {stats['total_loaded']:>9,} rows")
    L.append("")
    L.append("CLEANING SUMMARY:")
    L.append(f"  {'Null claim_text dropped:':<36} → {stats['null_dropped']:>9,} rows")
    L.append(f"  {'Duplicates removed:':<36} → {stats['dupes_removed']:>9,} rows")
    L.append(f"  {'Verdicts normalized:':<36} → {stats['verdicts_fixed']:>9,} values fixed")
    L.append(f"  {'Categories normalized:':<36} → {stats['categories_fixed']:>9,} values fixed")
    L.append(f"  {'Confidence scores fixed:':<36} → {stats['confidence_fixed']:>9,} values fixed")
    L.append(line)
    L.append(f"  {'FINAL CLEAN RECORDS:':<36} → {stats['final_records']:>9,} rows")
    L.append("")

    total = max(stats["final_records"], 1)
    L.append("VERDICT DISTRIBUTION:")
    for verdict in ("TRUE", "FALSE", "MISLEADING", "UNVERIFIED"):
        cnt = stats["verdict_dist"].get(verdict, 0)
        pct = cnt / total * 100
        L.append(f"  {VERDICT_ICONS[verdict]:<16} {cnt:>9,} ({pct:>4.1f}%)")
    L.append("")
    L.append("CATEGORY DISTRIBUTION:")
    for cat in ("Health", "Politics", "Science", "Technology", "Economy", "Other"):
        cnt = stats["category_dist"].get(cat, 0)
        pct = cnt / total * 100
        L.append(f"  {CATEGORY_ICONS[cat]:<16} {cnt:>9,} ({pct:>4.1f}%)")
    L.append("")
    L.append("OUTPUT FILES:")
    if stats["dry_run"]:
        L.append("  (dry-run: no files written)")
    else:
        L.append("  ✅ backend/data/processed/claims_clean.csv")
        L.append("  ✅ backend/data/processed/claims_clean.json")
        L.append("  ✅ backend/data/processed/consolidation_report.txt")
    L.append("=" * 60)
    L.append("  Data is ready for embedding generation!")
    L.append("  Next step: run python scripts/generate_embeddings.py")
    L.append("=" * 60)
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Main pipeline
# --------------------------------------------------------------------------- #
def run(raw_dir: Path, dry_run: bool) -> int:
    print(c("\n" + "=" * 60, CY))
    print(c("  FACT-CHECKER DATA CONSOLIDATION", CY))
    print(c("=" * 60, CY))
    LOG.info("Starting consolidation | raw_dir=%s | dry_run=%s", raw_dir, dry_run)

    if not raw_dir.exists():
        print(c(f"[ERROR] Input directory does not exist: {raw_dir}", RE))
        LOG.error("Input directory missing: %s", raw_dir)
        return 1

    files = discover_files(raw_dir)
    if not files:
        print(c(f"[ERROR] No supported data files found in {raw_dir}", RE))
        print(c("        Place your data files (.csv/.json/.tsv/.xlsx) there first.", YE))
        LOG.error("No files found in %s", raw_dir)
        return 1

    print(c(f"\nFound {len(files)} file(s) in {raw_dir}\n", GR))

    # ----- 1.1 Load + 1.2 Map columns ----------------------------------- #
    mapped_frames: List[pd.DataFrame] = []
    file_stats: List[Tuple[str, int]] = []

    for idx, path in enumerate(
        tqdm(files, desc="Loading files", unit="file"), start=1
    ):
        df = load_file(path)
        if df is None or df.empty:
            file_stats.append((path.name, 0))
            continue

        cols_preview = list(df.columns)[:6]
        print(
            c(f"[FILE {idx}] {path.name} → ", BL)
            + f"Shape: {df.shape} | Columns: {cols_preview}"
        )
        LOG.info("Loaded %s shape=%s columns=%s", path.name, df.shape, list(df.columns))

        mapped, mapping = map_columns(df)
        mapped["source_file"] = path.name
        mapped_frames.append(mapped)
        file_stats.append((path.name, len(df)))
        LOG.info("Column mapping for %s: %s", path.name, mapping)

    if not mapped_frames:
        print(c("[ERROR] No files could be loaded successfully.", RE))
        return 1

    # ----- 1.3 Combine --------------------------------------------------- #
    print(c("\nConcatenating all files...", CY))
    combined = pd.concat(mapped_frames, ignore_index=True)
    total_loaded = len(combined)
    LOG.info("Combined shape: %s", combined.shape)

    # ----- 1.4 Missing values ------------------------------------------- #
    print(c("Handling missing values...", CY))
    before_drop = len(combined)
    combined["claim_text"] = combined["claim_text"].apply(
        lambda x: x.strip() if isinstance(x, str) else x
    )
    combined = combined[
        combined["claim_text"].notna()
        & (combined["claim_text"].astype(str).str.strip() != "")
    ]
    null_dropped = before_drop - len(combined)
    combined = combined.reset_index(drop=True)

    for col, default in DEFAULTS.items():
        combined[col] = combined[col].where(
            combined[col].notna()
            & (combined[col].astype(str).str.strip() != ""),
            default,
        )

    # ----- 1.5 Normalize verdicts --------------------------------------- #
    print(c("Normalizing verdict labels...", CY))
    orig_verdict = combined["verdict"].astype(str).str.strip()
    combined["verdict"] = [
        normalize_verdict(v) for v in tqdm(
            combined["verdict"], desc="Verdicts", unit="row", leave=False
        )
    ]
    verdicts_fixed = int(
        (orig_verdict.str.upper() != combined["verdict"]).sum()
    )

    # ----- 1.6 Normalize categories ------------------------------------- #
    print(c("Normalizing category labels...", CY))
    orig_category = combined["category"].astype(str).str.strip()
    combined["category"] = [
        normalize_category(cat) for cat in tqdm(
            combined["category"], desc="Categories", unit="row", leave=False
        )
    ]
    categories_fixed = int((orig_category != combined["category"]).sum())

    # ----- 1.9 Validate confidence_score -------------------------------- #
    print(c("Validating confidence scores...", CY))
    conf_results = [fix_confidence(v) for v in combined["confidence_score"]]
    combined["confidence_score"] = [r[0] for r in conf_results]
    confidence_fixed = int(sum(1 for r in conf_results if r[1]))

    # ----- 1.7 Remove duplicates ---------------------------------------- #
    print(c("Removing duplicate claims...", CY))
    before_dupes = len(combined)
    dedup_key = combined["claim_text"].astype(str).str.strip().str.lower()
    combined = combined[~dedup_key.duplicated(keep="first")].reset_index(drop=True)
    dupes_removed = before_dupes - len(combined)

    # ----- 1.8 Generate unique claim IDs -------------------------------- #
    print(c("Generating unique claim IDs...", CY))
    combined.insert(
        0, "claim_id",
        [f"claim_{uuid.uuid4()}" for _ in range(len(combined))],
    )

    # ----- 1.10 Final column order -------------------------------------- #
    combined = combined[FINAL_COLUMNS]

    # ----- Stats -------------------------------------------------------- #
    stats = {
        "files": file_stats,
        "total_loaded": total_loaded,
        "null_dropped": null_dropped,
        "dupes_removed": dupes_removed,
        "verdicts_fixed": verdicts_fixed,
        "categories_fixed": categories_fixed,
        "confidence_fixed": confidence_fixed,
        "final_records": len(combined),
        "verdict_dist": combined["verdict"].value_counts().to_dict(),
        "category_dist": combined["category"].value_counts().to_dict(),
        "dry_run": dry_run,
    }

    # ----- 1.11 Export -------------------------------------------------- #
    if not dry_run:
        print(c("\nWriting output files...", CY))
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        combined.to_csv(CSV_OUT, index=False, encoding="utf-8")
        combined.to_json(JSON_OUT, orient="records", force_ascii=False, indent=2)
        LOG.info("Wrote %s and %s (%d rows)", CSV_OUT, JSON_OUT, len(combined))
    else:
        print(c("\n[DRY-RUN] Skipping file writes.", YE))

    # ----- 3. Report ---------------------------------------------------- #
    report = build_report(stats)
    print("\n" + report)

    if not dry_run:
        REPORT_OUT.write_text(report, encoding="utf-8")
        LOG.info("Wrote report to %s", REPORT_OUT)

    LOG.info(
        "Done | loaded=%d final=%d dropped=%d dupes=%d",
        total_loaded, len(combined), null_dropped, dupes_removed,
    )
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consolidate raw fact-check datasets into one clean dataset.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline and print the report without writing files.",
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default=str(DEFAULT_RAW_DIR),
        help=f"Override the input directory (default: {DEFAULT_RAW_DIR}).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    global LOG
    LOG = setup_logging()
    args = parse_args(argv)
    raw_dir = Path(args.input_dir).expanduser().resolve()
    try:
        return run(raw_dir, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Fatal error during consolidation")
        print(c(f"\n[FATAL] {exc}", RE))
        return 1


if __name__ == "__main__":
    sys.exit(main())
