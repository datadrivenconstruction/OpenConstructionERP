"""Schedule Intelligence Pydantic schemas — request / response shapes.

Phase 0 exposes the **governance surface** (locked figures + confidence config +
a confidence preview); Phase 1 adds the **readiness (Watch)** surface. The
remaining per-insight schemas (risk, decision) arrive with their engines in
Phases 2–4.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.schedule_intelligence.enums import (
    ConfidenceBand,
    LockedFigureType,
    ReadinessClass,
)


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


# ─────────────────────────────────────────────────────────────────────────────
# E1 — Readiness (Watch)
# ─────────────────────────────────────────────────────────────────────────────
class ReadinessEvaluateRequest(BaseModel):
    """Trigger a readiness evaluation for a look-ahead.

    ``today`` overrides the evaluation date (defaults to the server's UTC date);
    supplying it makes the deterministic ``evaluation_run_id`` reproducible in
    tests and back-dated re-runs.
    """

    today: date | None = None


class ReadinessDriver(BaseModel):
    """One traceable reason behind a classification (P4): links to a source row."""

    type: str
    ref: str
    detail: str


class ReadinessResultRead(BaseModel):
    """A persisted readiness snapshot row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    activity_ref: str
    look_ahead_ref: str | None
    classification: ReadinessClass
    binding_constraint_ref: str | None
    need_by_date: datetime | None
    planned_start_date: datetime | None
    total_float_days: int | None
    float_burn_days: int | None
    drivers: list[ReadinessDriver] = Field(default_factory=list)
    confidence_score: Decimal | None
    confidence_band: str | None
    confidence_rationale: list[dict[str, Any]] = Field(default_factory=list)
    evaluation_run_id: str | None
    created_at: datetime
    updated_at: datetime


class ReadinessRunResponse(BaseModel):
    """A whole readiness run: its id, per-class counts, and the rows."""

    evaluation_run_id: str | None
    look_ahead_ref: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    results: list[ReadinessResultRead] = Field(default_factory=list)
