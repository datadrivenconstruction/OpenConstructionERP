# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the retrieval (findability) API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RetrievalResultOut(BaseModel):
    """One ranked record with the provenance needed to reconstruct it."""

    record_type: str
    record_id: str
    title: str
    snippet: str
    source_module: str
    party: str
    occurred_at: str
    entity_refs: list[str]
    score: float
    matched_facets: list[str]
    provenance: dict


class RetrievalResponse(BaseModel):
    """A ranked, faceted view across the project record."""

    count: int
    results: list[RetrievalResultOut]


# ── Saved searches ───────────────────────────────────────────────────────────


class SavedSearchFacets(BaseModel):
    """The six facets a saved search replays, mirroring ``GET /search``.

    Every field is optional and defaults to empty, so a caller sends only the
    facets it cares about and the server fills the rest in as "unset".
    """

    text: str = Field(default="", max_length=500)
    party: str = Field(default="", max_length=200)
    record_type: str = Field(default="", max_length=50)
    date_from: str = Field(default="", max_length=10)
    date_to: str = Field(default="", max_length=10)
    entity: str = Field(default="", max_length=200)


class SavedSearchCreate(BaseModel):
    """Pin a search under a label.

    Saving facets that are already pinned updates that pin (label included)
    rather than adding a second identical row - the same behaviour the browser
    had, now enforced by a unique constraint instead of by array filtering.
    """

    project_id: uuid.UUID
    label: str = Field(default="", max_length=200)
    query: SavedSearchFacets = Field(default_factory=SavedSearchFacets)


class SavedSearchUpdate(BaseModel):
    """Rename a pin, or re-point it at different facets.

    Both fields are optional: sending only ``label`` renames, sending only
    ``query`` re-points, sending both does both.
    """

    label: str | None = Field(default=None, max_length=200)
    query: SavedSearchFacets | None = None


class SavedSearchFinding(BaseModel):
    """One failing validation rule, carried on the saved search that failed it."""

    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None


class SavedSearchOut(BaseModel):
    """A pinned search as the list and the detail views render it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    query: SavedSearchFacets
    signature: str
    use_count: int
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    validation_status: str
    validation_findings: list[SavedSearchFinding] = Field(default_factory=list)


class SavedSearchListResponse(BaseModel):
    """Every search the caller pinned on one project, most useful first."""

    count: int
    results: list[SavedSearchOut]
