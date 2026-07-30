"""
claims.py — CRUD stubs for individual claims.

These are placeholders for a future admin/curation flow. The read endpoints
serve from the consolidated CSV; write endpoints are intentionally not wired to
a datastore yet and return 501.
"""

import logging
from functools import lru_cache
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from config import settings
from models.claim import ClaimRecord

logger = logging.getLogger("routers.claims")

router = APIRouter(prefix="/api/claims", tags=["claims"])


# Defaults used to replace CSV NaNs so rows validate against ClaimRecord.
_FILL_DEFAULTS = {
    "verdict": "UNVERIFIED", "category": "Other", "confidence_score": 0.5,
    "source_url": "N/A", "evidence_url": "N/A", "timestamp": "", "source_file": "",
}


@lru_cache(maxsize=1)
def _load_df():
    path = settings.processed_csv
    if not path.exists():
        return None
    import pandas as pd

    df = pd.read_csv(path, low_memory=False)
    # Fill NaNs so Pydantic string fields don't choke on float('nan').
    for col, default in _FILL_DEFAULTS.items():
        if col in df.columns:
            df[col] = df[col].fillna(default)
    return df


@router.get("", response_model=List[ClaimRecord])
async def list_claims(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    verdict: Optional[str] = Query(None),
) -> List[ClaimRecord]:
    df = _load_df()
    if df is None:
        return []
    view = df
    if verdict:
        view = view[view["verdict"].str.upper() == verdict.upper()]
    page = view.iloc[offset: offset + limit]
    return [ClaimRecord(**row) for row in page.to_dict(orient="records")]


@router.get("/{claim_id}", response_model=ClaimRecord)
async def get_claim(claim_id: str) -> ClaimRecord:
    df = _load_df()
    if df is None:
        raise HTTPException(status_code=404, detail="No claims dataset loaded.")
    match = df[df["claim_id"] == claim_id]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found.")
    return ClaimRecord(**match.iloc[0].to_dict())


@router.post("", status_code=501)
async def create_claim() -> dict:
    raise HTTPException(status_code=501, detail="Creating claims is not implemented yet.")


@router.delete("/{claim_id}", status_code=501)
async def delete_claim(claim_id: str) -> dict:
    raise HTTPException(status_code=501, detail="Deleting claims is not implemented yet.")
