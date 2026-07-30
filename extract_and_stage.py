#!/usr/bin/env python
"""
extract_and_stage.py
====================

Pull ONLY the 6 selected datasets out of the ``files*.zip`` archives at the repo
root and stage them into ``backend/data/raw/`` under their original filenames.

The script does not hardcode which zip holds which file: it scans every ``*.zip``
in the repo root, lists the CSVs inside, and extracts any that match one of the
6 target filenames (exact, case-sensitive match on the basename).

Run:
    python extract_and_stage.py
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Unicode-safe stdout on Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

try:
    from colorama import Fore, Style
    from colorama import init as _colorama_init

    _colorama_init()

    def c(text: str, color: str = "") -> str:
        return f"{color}{text}{Style.RESET_ALL}" if color else text

    CY, GR, YE, RE = Fore.CYAN, Fore.GREEN, Fore.YELLOW, Fore.RED
except ImportError:  # pragma: no cover
    def c(text: str, color: str = "") -> str:  # type: ignore
        return text

    CY = GR = YE = RE = ""

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parent
RAW_DIR = REPO_ROOT / "backend" / "data" / "raw"

# Exact, case-sensitive target filenames.
TARGET_FILES: List[str] = [
    "FEVER_1_train_145449.csv",
    "MASTER_ALL_124756_claims_ALL_TOPICS_ALL_COUNTRIES.csv",
    "FACTSPAN_1_ALL_65090_claims_2007to2025.csv",
    "6_claimbuster_30270_claims.csv",
    "3_fakenewsnet_23196_claims.csv",
    "POLITIFACT_21152.csv",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def count_csv_rows(path: Path) -> int:
    """Return the number of data rows (excluding header). Robust to bad lines."""
    try:
        # Fast, low-memory: read only the first column.
        df = pd.read_csv(path, usecols=[0], on_bad_lines="skip", low_memory=False)
        return len(df)
    except Exception:
        # Fallback: raw line count minus header (may over/undercount on
        # embedded newlines, but never crashes).
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return max(sum(1 for _ in fh) - 1, 0)
        except OSError:
            return -1


def verify_not_corrupted(path: Path) -> bool:
    """Return True if the CSV opens cleanly (reads a single row)."""
    try:
        pd.read_csv(path, nrows=1, on_bad_lines="skip", low_memory=False)
        return True
    except Exception as exc:  # noqa: BLE001
        print(c(f"    [CORRUPT] {path.name}: {exc}", RE))
        return False


def find_zips(root: Path) -> List[Path]:
    return sorted(root.glob("*.zip"))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    zips = find_zips(REPO_ROOT)
    if not zips:
        print(c(f"[ERROR] No .zip files found in {REPO_ROOT}", RE))
        return 1

    remaining = set(TARGET_FILES)
    # name -> (row_count, status)  status in {extracted, skipped-exists}
    extracted: Dict[str, int] = {}
    skipped_existing: Dict[str, int] = {}

    for zpath in zips:
        print(c(f"Scanning {zpath.name}...", CY))
        try:
            zf = zipfile.ZipFile(zpath)
        except zipfile.BadZipFile:
            print(c(f"  [WARN] {zpath.name} is not a valid zip — skipping.", YE))
            continue

        with zf:
            # Map basename -> full member name (only .csv members).
            members = {
                os.path.basename(n): n
                for n in zf.namelist()
                if n.lower().endswith(".csv") and not n.endswith("/")
            }

            for target in TARGET_FILES:
                if target not in remaining:
                    continue  # already handled from an earlier zip
                if target not in members:
                    continue

                dest = RAW_DIR / target
                if dest.exists():
                    rows = count_csv_rows(dest)
                    skipped_existing[target] = rows
                    remaining.discard(target)
                    print(c(f"  ↷ Skip (exists): {target} ({rows} rows)", YE))
                    continue

                try:
                    data = zf.read(members[target])
                    dest.write_bytes(data)
                except Exception as exc:  # noqa: BLE001
                    print(c(f"  [ERROR] Failed to extract {target}: {exc}", RE))
                    continue

                rows = count_csv_rows(dest)
                extracted[target] = rows
                remaining.discard(target)
                print(c(f"  ✓ Found: {target} ({rows} rows)", GR))

    # --- Warn about any targets never found -------------------------------- #
    for missing in TARGET_FILES:
        if missing in remaining:
            print(c(f"[WARN] Target file never found in any zip: {missing}", YE))

    # --- Verification pass -------------------------------------------------- #
    print(c("\nVerifying extracted files...", CY))
    all_present = {**extracted, **skipped_existing}
    good = 0
    for name in all_present:
        path = RAW_DIR / name
        if path.exists() and verify_not_corrupted(path):
            good += 1

    total_rows = sum(v for v in all_present.values() if v > 0)

    # --- Summary ----------------------------------------------------------- #
    print(c("\n" + "=" * 44, CY))
    print(c("EXTRACTION COMPLETE", CY))
    print(c("=" * 44, CY))
    print(f"Files extracted:      {len(extracted)}")
    if skipped_existing:
        print(f"Files already staged: {len(skipped_existing)} (skipped)")
    print(f"Files verified OK:    {good}/{len(all_present)}")
    print(f"Total rows:           {total_rows:,}")
    print(f"Location:             {RAW_DIR}")
    print(c("=" * 44, CY))

    if remaining:
        print(c(f"\n[WARN] {len(remaining)} target file(s) missing — "
                f"pipeline will run on what was staged.", YE))
        return 2
    print(c("\nNext step: cd backend && python scripts/data_consolidation.py", GR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
