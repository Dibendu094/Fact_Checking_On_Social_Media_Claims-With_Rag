"""
main.py
=======

FastAPI application entrypoint for the Fact-Checker API.

Run:
    cd backend
    python -m uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure the emoji/Unicode startup banner prints on Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from config import settings
from routers import auth, claims, fact_check, health, search, stats


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def _configure_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.log_dir / "api.log", encoding="utf-8"),
        ],
    )


_configure_logging()
logger = logging.getLogger("main")

# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
app = FastAPI(
    title="Fact-Checker API",
    description="RAG-powered fact-checking over 484K+ claims "
                "(multilingual-e5-large + Pinecone + Groq).",
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router)
app.include_router(fact_check.router)
app.include_router(stats.router)
app.include_router(search.router)
app.include_router(claims.router)
app.include_router(auth.router)


@app.get("/", tags=["root"])
async def root() -> dict:
    return {
        "service": "fact-checker-api",
        "version": settings.app_version,
        "docs": "/docs",
        "endpoints": [
            "/health", "/api/fact-check", "/api/stats", "/api/search", "/api/claims",
        ],
    }


@app.on_event("startup")
async def _on_startup() -> None:
    print("\n🚀 Starting Fact-Check API...")
    logger.info("Fact-Check API starting (version %s)", settings.app_version)

    # Pinecone: verify the connection and report the live vector count.
    if settings.has_pinecone():
        try:
            from services.pinecone_service import get_pinecone_service

            stats_ = get_pinecone_service().index_stats()
            count = stats_.get("total_vector_count")
            print(f"✅ Pinecone connected ({count:,} vectors)" if count is not None
                  else "✅ Pinecone connected")
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  Pinecone connection failed: {exc}")
            logger.warning("Pinecone connection failed at startup: %s", exc)
    else:
        print("⚠️  PINECONE_API_KEY missing — /api/fact-check will return 503")

    if settings.has_groq():
        print(f"✅ Groq LLM configured (model '{settings.groq_model}')")
    else:
        print("⚠️  No LLM key (GROQ_API_KEY) — verdicts will fall back to UNVERIFIED")

    # The embedding model loads lazily on the first check (keeps startup fast).
    print(f"ℹ️  Embedding model '{settings.embedding_model}' loads on first request")

    if settings.enable_web_search:
        layers = "Google FC + DuckDuckGo" if settings.has_google_factcheck() else "DuckDuckGo only"
        print(f"✅ Web search enabled ({layers})")
    else:
        print("ℹ️  Web search disabled (ENABLE_WEB_SEARCH=false)")

    print("✅ API running on http://localhost:8000\n")
