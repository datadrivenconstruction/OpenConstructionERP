"""Schedule Intelligence Pydantic schemas — request / response shapes.

Phase 0 exposes only the **governance surface** (locked figures + confidence
config + a confidence preview). The per-insight schemas (readiness, risk,
decision) arrive with their engines in Phases 1–4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.schedule_intelligence.enums import ConfidenceBand, LockedFigureType


# ─────────────────────────────────────────────────────────────────────────────
# E5.2 — Locked figures
# ─────────────────────────────────────────────────────────────────────────────
class LockFigureRequest(BaseModel):
    """Request to lock a commercially-sensitive figure.

    ``value`` accepts any JSON scalar/container; the service canonicalises it
    (see ``locked_guard.canonical_value``) before comparison and storage, so
    ``5``, ``5.0`` and ``"5"`` are equivalent.
    """

    path: str = Field(min_length=1, max_length=255)
    figure_type: LockedFigureType
    value: Any
    source_ref: str | None = Field(default=None, max_length=64)
    reason: str = Field(default="", max_length=5000)


class LockedFigureRead(BaseModel):
    """A stored locked figure."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    path: str
    figure_type: str
    value: str
    value_hash: str
    source_ref: str | None
    reason: str
    active: bool
    locked_by: UUID | None
    locked_at: datetime
    unlocked_by: UUID | None
    unlocked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VerifyWritesRequest(BaseModel):
    """Dry-run a batch of proposed writes against the project's locked figures.

    Maps ``path -> proposed value``; the response reports which writes a real
    apply would reject. Read-only — persists nothing.
    """

    writes: dict[str, Any] = Field(default_factory=dict)


class WriteViolation(BaseModel):
    path: str
    locked_value: str
    attempted_value: str


class VerifyWritesResponse(BaseModel):
    ok: bool
    violations: list[WriteViolation] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# E5.3 — Confidence configuration + preview
# ─────────────────────────────────────────────────────────────────────────────
class ConfidenceConfigUpsert(BaseModel):
    """Create a new active version of a project's confidence gating policy.

    Any omitted map keeps the built-in default for that facet. Upsert always
    creates a new version and deactivates the prior one (versioned + audited).
    """

    description: str = Field(default="", max_length=5000)
    band_thresholds: dict[str, float] | None = None
    schedule_quality_caps: dict[str, float] | None = None
    feed_coverage_caps: dict[str, float] | None = None
    corroboration_bonuses: dict[str, float] | None = None


class ConfidenceConfigRead(BaseModel):
    """The resolved, active confidence policy for a project.

    ``source`` states where it came from: ``"project"`` (a project override),
    ``"global"`` (the deployment default row) or ``"default"`` (built-in
    fallback, no row yet) — never silent about which policy is in force.
    """

    source: str
    version: int | None
    band_thresholds: dict[str, float]
    schedule_quality_caps: dict[str, float]
    feed_coverage_caps: dict[str, float]
    corroboration_bonuses: dict[str, float]


class ConfidencePreviewRequest(BaseModel):
    """Inputs to compute a uniform confidence result under the active policy."""

    base_score: float = Field(ge=0.0, le=1.0)
    schedule_quality: str | None = None
    feed_coverage: str | None = None
    corroboration: list[str] = Field(default_factory=list)


class ConfidencePreviewResponse(BaseModel):
    score: float
    band: ConfidenceBand
    rationale: list[dict[str, Any]] = Field(default_factory=list)
