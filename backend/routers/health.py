"""GET /health — liveness, version, and dependency status."""

import logging

from fastapi import APIRouter

from config import settings
from models.claim import HealthResponse

logger = logging.getLogger("routers.health")

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    Reports configuration and live connectivity.

    The Pinecone check is a real round-trip; it degrades to ``False`` rather
    than failing the endpoint, so /health stays useful when a dep is down.
    """
    pinecone_ok = False
    vector_count = None
    if settings.has_pinecone():
        try:
            from services.pinecone_service import get_pinecone_service

            stats = get_pinecone_service().index_stats()
            vector_count = stats.get("total_vector_count")
            pinecone_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pinecone health check failed: %s", exc)

    # Report whether the embedding model is already resident (do not load it
    # here — that would make /health slow and memory-hungry).
    model_loaded = False
    try:
        from services.embedding_service import EmbeddingService

        model_loaded = getattr(EmbeddingService(), "_model", None) is not None
    except Exception:  # noqa: BLE001
        pass

    return HealthResponse(
        status="healthy" if (pinecone_ok and settings.has_llm()) else "degraded",
        service="fact-check-api",
        version=settings.app_version,
        web_search_active=settings.enable_web_search,
        pinecone_connected=pinecone_ok,
        llm_configured=settings.has_llm(),
        embedding_model_loaded=model_loaded,
        vector_count=vector_count,
    )
