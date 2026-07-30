"""GET /api/search — live web fact-check lookup, bypassing the vector index."""

import logging

from fastapi import APIRouter, HTTPException, Query

from services.web_search_service import get_web_search_service

logger = logging.getLogger("routers.search")

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
async def search(q: str = Query(..., min_length=3, max_length=1000)) -> dict:
    """Search published fact-checks (Google Fact Check API, then DuckDuckGo)."""
    try:
        result = await get_web_search_service().search(q)
        return {"query": q, **result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Web search failed")
        raise HTTPException(status_code=502, detail="Web search failed.") from exc
