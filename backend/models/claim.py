"""
Data structure definitions for the Fact-Checking RAG application.

Defines the canonical schema for a single fact-checked claim record plus the
request/response models used by the fact-check API. These models are the single
source of truth for the shape of the data flowing through the pipeline:

    raw files  ->  data_consolidation.py  ->  ClaimRecord  ->  embeddings/Pinecone
    user query ->  FactCheckRequest        ->  RAG          ->  FactCheckResponse
"""

from __future__ import annotations

import uuid
from typing import List, Optional

try:
    # Pydantic v2 (preferred, matches requirements.txt: pydantic==2.7.4)
    from pydantic import BaseModel, Field, field_validator

    _PYDANTIC_V2 = True
except ImportError:  # pragma: no cover - fallback for pydantic v1 environments
    from pydantic import BaseModel, Field, validator as _v1_validator  # type: ignore

    _PYDANTIC_V2 = False

from typing import Literal


# --------------------------------------------------------------------------- #
# Canonical vocabularies (kept in sync with data_consolidation.py)
# --------------------------------------------------------------------------- #
VERDICTS = ("TRUE", "FALSE", "MISLEADING", "UNVERIFIED")
CATEGORIES = ("Health", "Politics", "Science", "Technology", "Economy", "Other")

VerdictType = Literal["TRUE", "FALSE", "MISLEADING", "UNVERIFIED"]
CategoryType = Literal["Health", "Politics", "Science", "Technology", "Economy", "Other"]


# --------------------------------------------------------------------------- #
# Core record model
# --------------------------------------------------------------------------- #
class ClaimRecord(BaseModel):
    """A single, fully-cleaned fact-checked claim ready for embedding."""

    claim_id: str = Field(default_factory=lambda: f"claim_{uuid.uuid4()}")
    claim_text: str = Field(
        ...,
        min_length=5,
        max_length=5000,
        description="The actual social media claim text",
    )
    verdict: VerdictType = Field(
        default="UNVERIFIED",
        description="Fact-check verdict for the claim",
    )
    category: CategoryType = Field(
        default="Other",
        description="Topic category of the claim",
    )
    confidence_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence level of the verdict (0.0 to 1.0)",
    )
    source_url: Optional[str] = Field(
        default="N/A",
        description="Original URL where the claim appeared (tweet, news, etc.)",
    )
    evidence_url: Optional[str] = Field(
        default="N/A",
        description="URL of the fact-check article or evidence source",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="Date when the claim was published or fact-checked (YYYY-MM-DD)",
    )
    source_file: Optional[str] = Field(
        default=None,
        description="Which of the original files this record came from",
    )

    # -- validators ---------------------------------------------------------- #
    if _PYDANTIC_V2:

        @field_validator("claim_text")
        @classmethod
        def _strip_claim_text(cls, v: str) -> str:
            return v.strip() if isinstance(v, str) else v

    else:  # pragma: no cover

        @_v1_validator("claim_text")
        def _strip_claim_text(cls, v: str) -> str:  # noqa: N805
            return v.strip() if isinstance(v, str) else v


# --------------------------------------------------------------------------- #
# API request / response models
# --------------------------------------------------------------------------- #
class FactCheckRequest(BaseModel):
    """Incoming request: a user submits a claim to be fact-checked."""

    claim: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="The claim text to fact-check",
    )


class SimilarClaim(BaseModel):
    """A single retrieved neighbour returned alongside the verdict."""

    claim_text: str
    verdict: str
    category: str
    similarity_score: float
    source_url: str
    evidence_url: str


class WebSource(BaseModel):
    """A real, linkable published fact-check found via live web search."""

    publisher: str = Field(default="", description="Fact-checking organisation")
    title: str = Field(default="", description="Headline of the fact-check article")
    url: str = Field(default="", description="Link to the fact-check")
    verdict: Optional[str] = Field(default=None, description="Publisher's own rating")


ConfidenceTier = Literal["HIGH", "MEDIUM", "LOW", "VERY_LOW"]


class FactCheckResponse(BaseModel):
    """Full response returned to the user after RAG fact-checking."""

    claim: str
    verdict: VerdictType
    confidence: int = Field(..., ge=0, le=100)
    explanation: str
    key_points: List[str]
    recommendation: str
    similar_claims: List[SimilarClaim]
    processing_time_ms: int

    # --- 3-tier routing metadata ---
    confidence_tier: ConfidenceTier = Field(
        default="VERY_LOW",
        description="HIGH=index match, MEDIUM=partial+web, LOW=web primary, "
                    "VERY_LOW=nothing found",
    )
    tier_reason: str = Field(default="", description="Why this tier was chosen")
    web_search_used: bool = Field(default=False)
    sources: List[WebSource] = Field(
        default_factory=list,
        description="Real published fact-checks to link the reader to",
    )
    # Convenience mirrors of the top source (kept for API compatibility).
    fact_check_url: Optional[str] = Field(default=None)
    fact_checker_org: Optional[str] = Field(default=None)


class StatsResponse(BaseModel):
    """
    Aggregate database statistics.

    total_claims reflects the live Pinecone index — the number actually used
    for retrieval, and the true size of the database. verdict_distribution /
    category_distribution / accuracy_rate are computed from the local labeled
    dataset only (claims_indexed_locally): claims uploaded to Pinecone from a
    separate batch (e.g. a Colab GPU run) are searchable but don't have local
    verdict/category rows to aggregate, so they're deliberately excluded from
    those breakdowns rather than guessed at.
    """

    total_claims: int = Field(
        ..., description="Total vectors in the live Pinecone index (source of truth)."
    )
    claims_indexed_locally: int = Field(
        ..., description="Rows in claims_clean.csv — the subset backing the "
                          "distributions below. Can be less than total_claims."
    )
    verdict_distribution: dict
    category_distribution: dict
    accuracy_rate: float = Field(
        ...,
        description="Share of locally-indexed claims with a definitive "
                    "(non-UNVERIFIED) verdict, as a %",
    )
    total_checks_today: int = 0
    web_search_enabled: bool = False


class HealthResponse(BaseModel):
    """Liveness / version / dependency status."""

    status: str = "healthy"
    service: str = "fact-check-api"
    version: str = "2.0.0"
    web_search_active: bool = False
    pinecone_connected: bool = False
    llm_configured: bool = False
    embedding_model_loaded: bool = False
    vector_count: Optional[int] = None


__all__ = [
    "ClaimRecord",
    "FactCheckRequest",
    "SimilarClaim",
    "WebSource",
    "FactCheckResponse",
    "StatsResponse",
    "HealthResponse",
    "ConfidenceTier",
    "VERDICTS",
    "CATEGORIES",
]
