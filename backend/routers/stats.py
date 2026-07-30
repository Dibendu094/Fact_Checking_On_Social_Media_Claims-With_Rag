"""GET /api/stats — dashboard aggregates computed from the consolidated CSV."""

import logging
from functools import lru_cache

from fastapi import APIRouter

from config import settings
from models.claim import StatsResponse

logger = logging.getLogger("routers.stats")

router = APIRouter(prefix="/api", tags=["stats"])

_DEFINITIVE = {"TRUE", "FALSE", "MISLEADING"}


# Hardcoded from consolidation_report.txt — used as fallback on Render where
# claims_clean.csv is gitignored and not present.
_HARDCODED_STATS = {
    "claims_indexed_locally": 259648,
    "verdict_distribution": {
        "TRUE": 125491,
        "FALSE": 82338,
        "MISLEADING": 16400,
        "UNVERIFIED": 35419,
    },
    "category_distribution": {
        "Other": 208598,
        "Technology": 20735,
        "Politics": 14165,
        "Health": 10786,
        "Economy": 4849,
        "Science": 515,
    },
    "accuracy_rate": 86.3,
}


@lru_cache(maxsize=1)
def _compute_local_stats() -> dict:
    """Load verdict/category columns from the local CSV once and cache the aggregates."""
    path = settings.processed_csv
    if not path.exists():
        logger.info(
            "claims_clean.csv not found at %s; using hardcoded dataset stats.", path
        )
        return _HARDCODED_STATS

    import pandas as pd

    df = pd.read_csv(path, usecols=["verdict", "category"], low_memory=False)
    total = int(len(df))
    verdicts = {k: int(v) for k, v in df["verdict"].value_counts().items()}
    categories = {k: int(v) for k, v in df["category"].value_counts().items()}
    definitive = sum(v for k, v in verdicts.items() if k in _DEFINITIVE)
    accuracy = round(definitive / total * 100, 1) if total else 0.0

    logger.info("Computed local stats: claims_indexed_locally=%d verdicts=%s", total, verdicts)
    return {
        "claims_indexed_locally": total,
        "verdict_distribution": verdicts,
        "category_distribution": categories,
        "accuracy_rate": accuracy,
    }


def _pinecone_total() -> int:
    """
    Live vector count from Pinecone — the true database size, since claims
    uploaded from a separate batch (outside claims_clean.csv) are still
    searchable. Falls back to the local count if Pinecone isn't reachable,
    so /api/stats never hard-fails over this.
    """
    try:
        from services.pinecone_service import get_pinecone_service

        stats = get_pinecone_service().index_stats()
        count = stats.get("total_vector_count")
        if isinstance(count, int):
            return count
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch Pinecone index stats: %s", exc)
    return _compute_local_stats()["claims_indexed_locally"]


# Simple in-process counter; resets on restart (no datastore by design).
_CHECKS_TODAY = {"date": None, "count": 0}


def record_check() -> None:
    """Called by the fact-check router after each successful check."""
    from datetime import date

    today = date.today()
    if _CHECKS_TODAY["date"] != today:
        _CHECKS_TODAY["date"] = today
        _CHECKS_TODAY["count"] = 0
    _CHECKS_TODAY["count"] += 1


@router.get("/stats", response_model=StatsResponse)
async def stats() -> StatsResponse:
    from datetime import date

    data = dict(_compute_local_stats())
    data["total_claims"] = _pinecone_total()
    today = date.today()
    data["total_checks_today"] = (
        _CHECKS_TODAY["count"] if _CHECKS_TODAY["date"] == today else 0
    )
    data["web_search_enabled"] = settings.enable_web_search
    return StatsResponse(**data)
