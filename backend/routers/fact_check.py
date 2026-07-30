"""POST /api/fact-check — run a claim through the RAG pipeline."""

import logging

from fastapi import APIRouter, HTTPException

from models.claim import FactCheckRequest, FactCheckResponse
from services.rag_pipeline import get_rag_pipeline

logger = logging.getLogger("routers.fact_check")

router = APIRouter(prefix="/api", tags=["fact-check"])


@router.post("/fact-check", response_model=FactCheckResponse)
async def fact_check(request: FactCheckRequest) -> FactCheckResponse:
    """
    Fact-check a single claim.

    Validation (10–1000 chars) is enforced by ``FactCheckRequest`` and returns
    422 automatically. Runtime/config failures surface as 503.
    """
    try:
        pipeline = get_rag_pipeline()
        result = await pipeline.fact_check(request.claim)
        try:
            from routers.stats import record_check

            record_check()
        except Exception:  # noqa: BLE001 - counting must never break a check
            pass
        return FactCheckResponse(**result)
    except (RuntimeError, ImportError) as exc:
        # Missing keys, uninstalled ML deps, or otherwise unconfigured services.
        logger.error("Service not configured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Fact-check service is not fully configured: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during fact-check")
        raise HTTPException(
            status_code=500, detail="Internal error while fact-checking the claim."
        ) from exc
