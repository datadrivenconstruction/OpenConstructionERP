"""Pydantic schemas for the unified search API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UnifiedSearchHit(BaseModel):
    """One semantic-search hit returned by the unified search endpoint."""

    id: str
    score: float = Field(..., ge=0.0, description="Fused RRF score (relative)")
    title: str
    snippet: str
    text: str
    module: str
    project_id: str = ""
    tenant_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    collection: str

    @property
    def source_type(self) -> str:
        """Alias for ``module`` — the canonical key the frontend uses to
        decide which native page to navigate to on click."""
        return self.module


class UnifiedSearchResponse(BaseModel):
    """Response envelope for ``GET /api/v1/search/``."""

    query: str
    types: list[str]
    project_id: str | None = None
    total: int
    hits: list[UnifiedSearchHit]
    facets: dict[str, int] = Field(
        default_factory=dict,
        description="Per-collection hit counts before final-limit truncation",
    )


class CollectionStatusItem(BaseModel):
    collection: str
    label: str
    vectors_count: int
    ready: bool


class SearchStatusResponse(BaseModel):
    """Aggregated status for the unified search service."""

    backend: str = ""
    engine: str = ""
    model_name: str = ""
    embedding_dim: int = 0
    connected: bool = False
    collections: list[CollectionStatusItem] = Field(default_factory=list)
    cost_collection: dict[str, Any] | None = None
