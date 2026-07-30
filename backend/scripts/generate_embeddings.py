#!/usr/bin/env python
"""
generate_embeddings.py
======================

Embed every cleaned claim from ``claims_clean.csv`` with the multilingual
``intfloat/multilingual-e5-large`` model and upsert the vectors (+ 8-field
metadata) into a Pinecone serverless index for RAG retrieval.

Important note on dimension
---------------------------
``intfloat/multilingual-e5-large`` produces **1024-dim** vectors (only the
*-base* variant is 768-dim). This script therefore reads the real embedding
dimension from the model at runtime and creates the Pinecone index to match,
warning loudly if it differs from ``--dimension``. Never hardcode 768 for the
large model — every upsert would be rejected.

e5 prefix convention
--------------------
e5 models expect ``passage: `` in front of stored documents and ``query: ``
in front of search queries. Both are applied automatically.

Configuration (env, e.g. via ``backend/.env``)
----------------------------------------------
    PINECONE_API_KEY   (required for a real run)
    PINECONE_INDEX     default: fact-check-claims
    PINECONE_CLOUD     default: aws
    PINECONE_REGION    default: us-east-1

Usage
-----
    python backend/scripts/generate_embeddings.py --dry-run            # local, no upload
    python backend/scripts/generate_embeddings.py                      # full run -> Pinecone
    python backend/scripts/generate_embeddings.py --skip-rows 5000     # resume after a crash
    python backend/scripts/generate_embeddings.py --batch-size 128
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

# Unicode-safe stdout on Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

try:
    from tqdm import tqdm  # noqa: F401  (imported for parity / optional use)
except ImportError:  # pragma: no cover
    pass

try:
    from colorama import Fore, Style
    from colorama import init as _colorama_init

    _colorama_init()

    def c(text: str, color: str = "") -> str:
        return f"{color}{text}{Style.RESET_ALL}" if color else text

    CY, GR, YE, RE, BL = Fore.CYAN, Fore.GREEN, Fore.YELLOW, Fore.RED, Fore.BLUE
except ImportError:  # pragma: no cover
    def c(text: str, color: str = "") -> str:  # type: ignore
        return text

    CY = GR = YE = RE = BL = ""

# --------------------------------------------------------------------------- #
# Paths & defaults
# --------------------------------------------------------------------------- #
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
PROCESSED_DIR = BACKEND_DIR / "data" / "processed"
LOG_DIR = BACKEND_DIR / "logs"

DEFAULT_INPUT = PROCESSED_DIR / "claims_clean.csv"
CHECKPOINT_FILE = PROCESSED_DIR / ".embed_checkpoint.json"
GEN_LOG_FILE = LOG_DIR / "embedding_generation.log"
ERR_LOG_FILE = LOG_DIR / "embedding_errors.log"

DEFAULT_MODEL = "intfloat/multilingual-e5-large"   # 1024-dim
EXPECTED_DIM = 768                                  # per spec; e5-large is actually 1024
METRIC = "cosine"

DEFAULT_INDEX = os.getenv("PINECONE_INDEX", "fact-check-claims")
DEFAULT_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
DEFAULT_REGION = os.getenv("PINECONE_REGION", "us-east-1")
DEFAULT_NAMESPACE = "claims"

MAX_META_CHARS = 500  # claim_text stored in metadata (keeps vectors well under 40 KB)

LOG = logging.getLogger("generate_embeddings")


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("generate_embeddings")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(GEN_LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(fh)
    return logger


def log_batch_error(batch_start: int, batch_end: int, exc: Exception) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    with open(ERR_LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(f"{ts} | Batch {batch_start}-{batch_end}: {exc}\n")


def load_dotenv_if_present() -> None:
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        return
    except ImportError:
        pass
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def detect_device(requested: Optional[str]) -> str:
    if requested:
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_claims(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(
            f"Input not found: {input_path}\n"
            f"Run data_consolidation.py first to produce claims_clean.csv."
        )
    df = (
        pd.read_json(input_path)
        if input_path.suffix.lower() == ".json"
        else pd.read_csv(input_path, low_memory=False)
    )
    for col in ("claim_id", "claim_text"):
        if col not in df.columns:
            raise ValueError(f"Input missing required column: {col}")
    defaults = {
        "verdict": "UNVERIFIED", "category": "Other", "confidence_score": 0.5,
        "source_url": "N/A", "evidence_url": "N/A", "timestamp": "", "source_file": "",
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
    return df.reset_index(drop=True)


def build_metadata(row: pd.Series) -> dict:
    try:
        conf = float(row["confidence_score"])
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "claim_text": str(row["claim_text"])[:MAX_META_CHARS],
        "verdict": str(row["verdict"]),
        "category": str(row["category"]),
        "confidence_score": conf,
        "source_url": str(row["source_url"]),
        "evidence_url": str(row["evidence_url"]),
        "timestamp": str(row["timestamp"]),
        "source_file": str(row["source_file"]),
    }


# --------------------------------------------------------------------------- #
# Checkpoint (best-effort resume aid; --skip-rows is the primary control)
# --------------------------------------------------------------------------- #
def save_checkpoint(input_path: Path, total: int, next_index: int) -> None:
    try:
        CHECKPOINT_FILE.write_text(
            json.dumps({"input": str(input_path), "total": total,
                        "next_index": next_index}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Model / Pinecone
# --------------------------------------------------------------------------- #
def get_embedder(model_name: str, device: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            c("[ERROR] sentence-transformers is not installed.\n", RE)
            + "        pip install sentence-transformers"
        ) from exc
    print(c(f"Loading model '{model_name}' on device '{device}' "
            f"(first run downloads ~2.3GB)...", CY))
    model = SentenceTransformer(model_name, device=device)
    dim = model.get_sentence_embedding_dimension()
    print(c(f"Model loaded. Embedding dimension = {dim}.", GR))
    return model, dim


def get_pinecone_index(index_name: str, dim: int, cloud: str, region: str):
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        raise SystemExit(
            c("[ERROR] PINECONE_API_KEY not set.\n", RE)
            + "        Set it in backend/.env or the environment, "
            "or use --dry-run to test locally."
        )
    try:
        from pinecone import Pinecone, ServerlessSpec
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            c("[ERROR] pinecone client is not installed.\n", RE)
            + "        pip install pinecone-client"
        ) from exc

    pc = Pinecone(api_key=api_key)
    try:
        names = pc.list_indexes().names()
    except AttributeError:  # older/newer client shape
        names = [i["name"] for i in pc.list_indexes()]

    if index_name not in names:
        print(c(f"Creating Pinecone index '{index_name}' (dim={dim}, {METRIC})...", CY))
        pc.create_index(
            name=index_name, dimension=dim, metric=METRIC,
            spec=ServerlessSpec(cloud=cloud, region=region),
        )
        LOG.info("Created index %s dim=%d", index_name, dim)
    else:
        print(c(f"Using existing Pinecone index '{index_name}'.", GR))
    return pc.Index(index_name)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    print(c("\n" + "=" * 60, CY))
    print(c("  FACT-CHECKER EMBEDDING GENERATION (e5-large)", CY))
    print(c("=" * 60, CY))

    input_path = Path(args.input).expanduser().resolve()
    df = load_claims(input_path)
    total_rows = len(df)
    print(c(f"\nLoaded {total_rows:,} claims from {input_path.name}", GR))
    LOG.info("Loaded %d claims from %s", total_rows, input_path)

    device = detect_device(args.device)
    print(c(f"Compute device: {device}"
            + ("  (GPU detected)" if device == "cuda" else "  (CPU — slower)"),
            BL))

    model, dim = get_embedder(args.model, device)

    # Dimension sanity check vs the spec's 768.
    if dim != args.dimension:
        print(c(
            f"[WARN] Model dimension is {dim}, but --dimension={args.dimension}. "
            f"Using the MODEL's {dim} for the index (a mismatch would break upserts).",
            YE,
        ))
        LOG.warning("Dimension mismatch: model=%d requested=%d", dim, args.dimension)

    # ---- Dry run: embed one batch locally, do NOT upload ------------------ #
    if args.dry_run:
        n = min(args.batch_size, total_rows)
        print(c(f"\n[DRY-RUN] Embedding first {n} rows (no Pinecone)...", YE))
        texts = [f"passage: {t}" for t in df["claim_text"].astype(str).head(n)]
        t0 = time.time()
        embs = model.encode(texts, batch_size=args.batch_size,
                            normalize_embeddings=True, show_progress_bar=True)
        dt = time.time() - t0
        print(c(f"[DRY-RUN] {len(embs)} vectors of dim {len(embs[0])} "
                f"in {dt:.1f}s ({n/dt:.1f} rows/s).", GR))
        print(c("[DRY-RUN] Sample metadata (row 0):", CY))
        print("  " + json.dumps(build_metadata(df.iloc[0]), ensure_ascii=False)[:400])
        print(c("\n[DRY-RUN] OK — nothing sent to Pinecone.", GR))
        LOG.info("Dry-run: embedded %d rows dim=%d", len(embs), dim)
        return 0

    # ---- Real run -------------------------------------------------------- #
    index = get_pinecone_index(args.index_name, dim, args.cloud, args.region)

    start = max(args.skip_rows, 0)
    if start >= total_rows:
        print(c(f"--skip-rows ({start}) >= total rows ({total_rows}). Nothing to do.", YE))
        return 0
    if start:
        print(c(f"Skipping first {start:,} rows (resume mode).", YE))

    print(c(f"\nEmbedding + upserting rows {start:,}..{total_rows:,} "
            f"into namespace '{args.namespace}' (batch={args.batch_size})...\n", CY))
    LOG.info("Start upload: from=%d total=%d batch=%d namespace=%s",
             start, total_rows, args.batch_size, args.namespace)

    start_time = time.time()
    uploaded = start
    failed_batches = 0

    for i in range(start, total_rows, args.batch_size):
        batch = df.iloc[i: i + args.batch_size]
        texts = [f"passage: {t}" for t in batch["claim_text"].astype(str)]

        try:
            embeddings = model.encode(
                texts, batch_size=args.batch_size,
                normalize_embeddings=True, show_progress_bar=False,
            )
            vectors = [
                {
                    "id": str(row["claim_id"]),
                    "values": embeddings[j].tolist(),
                    "metadata": build_metadata(row),
                }
                for j, (_, row) in enumerate(batch.iterrows())
            ]
            index.upsert(vectors=vectors, namespace=args.namespace)

            uploaded = min(i + args.batch_size, total_rows)
            save_checkpoint(input_path, total_rows, uploaded)

            elapsed = time.time() - start_time
            done_this_run = uploaded - start
            rate = done_this_run / elapsed if elapsed > 0 else 0.0
            eta_min = ((total_rows - uploaded) / rate / 60) if rate > 0 else 0.0
            pct = uploaded / total_rows * 100
            print(f"[{uploaded:>7}/{total_rows}] {pct:5.1f}% | "
                  f"Speed: {rate:5.1f} rows/s | ETA: {eta_min:5.1f} min")

        except KeyboardInterrupt:
            print(c(f"\n[INTERRUPTED] Stopped at row {uploaded:,}. "
                    f"Resume with:  --skip-rows {uploaded}", YE))
            LOG.warning("Interrupted at row %d", uploaded)
            return 130
        except Exception as exc:  # noqa: BLE001 - log and continue
            failed_batches += 1
            print(c(f"ERROR: batch {i}-{i + args.batch_size} failed: {exc}", RE))
            log_batch_error(i, i + args.batch_size, exc)
            LOG.error("Batch %d-%d failed: %s", i, i + args.batch_size, exc)
            continue

    print(c(f"\n✅ Upload finished. Uploaded up to row {uploaded:,}. "
            f"Failed batches: {failed_batches}.", GR))
    LOG.info("Upload finished: uploaded=%d failed_batches=%d", uploaded, failed_batches)

    # ---- Verification + test search -------------------------------------- #
    verify_and_test(index, model, args.namespace)
    return 0


def verify_and_test(index, model, namespace: str) -> None:
    print(c("\nFinal Pinecone stats:", CY))
    try:
        stats = index.describe_index_stats()
        get = (lambda k: stats.get(k) if isinstance(stats, dict) else getattr(stats, k, None))
        print(f"  Total vectors: {get('total_vector_count'):,}")
        print(f"  Dimension:     {get('dimension')}")
        fullness = get("index_fullness")
        if fullness is not None:
            print(f"  Index fullness: {fullness:.1%}")
    except Exception as exc:  # noqa: BLE001
        print(c(f"  [WARN] Could not fetch stats: {exc}", YE))

    test_claim = "COVID vaccine causes autism"
    print(c(f"\nTest search: '{test_claim}'", CY))
    try:
        q = model.encode([f"query: {test_claim}"], normalize_embeddings=True)[0]
        results = index.query(vector=q.tolist(), top_k=3,
                              include_metadata=True, namespace=namespace)
        matches = results.get("matches") if isinstance(results, dict) else results.matches
        for rank, m in enumerate(matches or [], 1):
            md = m.get("metadata") if isinstance(m, dict) else m.metadata
            score = m.get("score") if isinstance(m, dict) else m.score
            text = (md or {}).get("claim_text", "")[:100]
            print(f"  {rank}. [Score: {score:.3f}] {text}...")
    except Exception as exc:  # noqa: BLE001
        print(c(f"  [WARN] Test search failed: {exc}", YE))

    print(c("\n" + "=" * 60, CY))
    print(c("  Embeddings uploaded. RAG index is ready to query!", GR))
    print(c("=" * 60, CY))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Embed cleaned claims with e5-large and upsert to Pinecone.",
    )
    p.add_argument("--input", default=str(DEFAULT_INPUT),
                   help=f"Input CSV/JSON (default: {DEFAULT_INPUT}).")
    p.add_argument("--batch-size", type=int, default=100,
                   help="Rows per embed+upsert batch (default: 100).")
    p.add_argument("--skip-rows", type=int, default=0,
                   help="Skip first N rows (resume an interrupted run).")
    p.add_argument("--dry-run", action="store_true",
                   help="Embed the first batch locally; do NOT upload.")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"sentence-transformers model (default: {DEFAULT_MODEL}).")
    p.add_argument("--device", default=None,
                   help="Torch device 'cuda'/'cpu' (default: auto-detect).")
    p.add_argument("--dimension", type=int, default=EXPECTED_DIM,
                   help=f"Expected index dim (default: {EXPECTED_DIM}); the model's "
                        "actual dim always wins to keep upserts valid.")
    p.add_argument("--index-name", default=DEFAULT_INDEX,
                   help=f"Pinecone index name (default: {DEFAULT_INDEX}).")
    p.add_argument("--namespace", default=DEFAULT_NAMESPACE,
                   help=f"Pinecone namespace (default: {DEFAULT_NAMESPACE}).")
    p.add_argument("--cloud", default=DEFAULT_CLOUD,
                   help=f"Serverless cloud (default: {DEFAULT_CLOUD}).")
    p.add_argument("--region", default=DEFAULT_REGION,
                   help=f"Serverless region (default: {DEFAULT_REGION}).")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    global LOG
    LOG = setup_logging()
    load_dotenv_if_present()
    args = parse_args(argv)
    try:
        return run(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Fatal error during embedding generation")
        print(c(f"\n[FATAL] {exc}", RE))
        return 1


if __name__ == "__main__":
    sys.exit(main())
