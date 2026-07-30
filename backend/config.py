"""
config.py
=========

Central application settings, loaded from environment variables (and
``backend/.env`` if present). Import ``settings`` anywhere:

    from config import settings
    settings.pinecone_index_name
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent

# Load backend/.env early (no hard dependency on python-dotenv).
_env_path = BACKEND_DIR / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv

        # override=True: the project's .env is authoritative. Without this, a
        # stale shell env var (e.g. a leftover GROQ_API_KEY) silently shadows
        # the .env value and causes confusing 401s.
        load_dotenv(_env_path, override=True)
    except ImportError:  # pragma: no cover
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ[_k.strip()] = _v.strip().strip('"').strip("'")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Settings:
    """Immutable-ish settings holder populated from the environment."""

    def __init__(self) -> None:
        # --- Pinecone ---
        self.pinecone_api_key: str = _get("PINECONE_API_KEY")
        self.pinecone_index_name: str = _get("PINECONE_INDEX_NAME", "fact-check-claims")
        self.pinecone_cloud: str = _get("PINECONE_CLOUD", "aws")
        self.pinecone_region: str = _get("PINECONE_REGION", "us-east-1")
        self.pinecone_namespace: str = _get("PINECONE_NAMESPACE", "claims")

        # --- LLM: Groq (active provider) ---
        self.groq_api_key: str = _get("GROQ_API_KEY")
        self.groq_model: str = _get("GROQ_MODEL", "llama-3.3-70b-versatile")

        # --- Web search (Google Fact Check Tools API + DuckDuckGo fallback) ---
        self.google_api_key: str = _get("GOOGLE_API_KEY")
        self.enable_web_search: bool = _get("ENABLE_WEB_SEARCH", "true").lower() in (
            "1", "true", "yes", "on"
        )

        # --- Embeddings ---
        self.embedding_model: str = _get("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
        self.embedding_dimension: int = _get_int("EMBEDDING_DIMENSION", 1024)

        # --- Retrieval ---
        self.top_k_results: int = _get_int("TOP_K_RESULTS", 5)
        self.similarity_threshold: float = _get_float("SIMILARITY_THRESHOLD", 0.82)
        # Tier routing: >= high -> Tier 1 (index only); >= medium -> Tier 2
        # (index + web); below -> Tier 3 (web primary).
        # NOTE: calibrated for multilingual-e5-large, which compresses cosine
        # similarity into a narrow high band (unrelated text still scores
        # ~0.83-0.85; genuine matches ~0.88+). Generic 0.80/0.60 thresholds
        # would route every claim to Tier 1 and web search would never fire.
        self.high_conf_threshold: float = _get_float("HIGH_CONF_THRESHOLD", 0.88)
        self.medium_conf_threshold: float = _get_float("MEDIUM_CONF_THRESHOLD", 0.86)

        # --- Supabase (admin password reset) ---
        self.supabase_url: str = _get("SUPABASE_URL")
        self.supabase_service_role_key: str = _get("SUPABASE_SERVICE_ROLE_KEY")

        # --- App ---
        self.log_level: str = _get("LOG_LEVEL", "INFO").upper()
        self.app_version: str = _get("APP_VERSION", "1.0.0")
        # Comma-separated list of allowed CORS origins.
        self.cors_origins: list[str] = [
            o.strip() for o in _get(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",") if o.strip()
        ]

        # --- Paths ---
        self.processed_csv: Path = BACKEND_DIR / "data" / "processed" / "claims_clean.csv"
        self.log_dir: Path = BACKEND_DIR / "logs"

    def has_pinecone(self) -> bool:
        return bool(self.pinecone_api_key)

    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    def has_llm(self) -> bool:
        return bool(self.groq_api_key)

    def has_google_factcheck(self) -> bool:
        """Google Fact Check Tools API needs its own key; DuckDuckGo does not."""
        return bool(self.google_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
