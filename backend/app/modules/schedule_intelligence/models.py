# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Schedule Intelligence ORM models.

This module is a **thin orchestration + governance layer** over the existing
``schedule_advanced`` / ``risk`` / ``variations`` / ``contracts`` / ``full_evm``
modules. It therefore owns very little state of its own: its tables hold the
*derived* insights (readiness, forward risk, priced decisions) and the
*governance* records (locked figures, confidence configuration) that no other
module produces.

Reuse boundary (see plan Key risks):
    Rows that already live elsewhere — a ``schedule_advanced`` ``delay_event``,
    a ``constraint``, a ``look_ahead`` activity — are referenced by their **id
    as a string ref**, never copied. There is exactly one source of truth per
    fact; these tables link to it. Refs are stored as ``String`` (not FK)
    because the target lives in a sibling module that this one must not
    hard-couple to at the DB level.

Tables (all prefixed ``oe_schedule_intelligence_``):
    confidence_config  — E5.3 config-as-data gating (caps / bonuses / bands)
    locked_figure      — E5.2 commercially-locked figures (policy-as-code guard)
    readiness_result   — E1 Ready/At-risk/Blocked per look-ahead activity
    risk_score         — E2 forward-risk composite (0..1) + band
    risk_factor        — E2 per-factor decomposition rows (P4 traceability)
    decision           — E4 claim-vs-accelerate priced options

``Base`` already provides ``id`` (UUID PK), ``created_at`` and ``updated_at`` —
do NOT redeclare them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


# ─────────────────────────────────────────────────────────────────────────────
# E5.3 — Confidence configuration (config-as-data gating)
# ─────────────────────────────────────────────────────────────────────────────
class ConfidenceConfig(Base):
    """Versioned, per-deployment confidence gating policy.

    The confidence framework (``confidence.py``) reads the active row and
    applies its caps/bonuses to every insight so that degraded feeds surface a
    reduced, *explained* confidence instead of a silent one (spec P5). A row
    with ``project_id IS NULL`` is the deployment-wide default; a project row
    overrides it. Thresholds are config-as-data (E2.1-AC7): versioned and
    audit-logged, never hard-coded in an engine.
    """

    __tablename__ = "oe_schedule_intelligence_confidence_config"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "version",
            name="uq_sched_intel_confidence_config_project_version",
        ),
    )

    # NULL project_id = deployment-wide default policy.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Band cutoffs on the final 0..1 confidence score, e.g.
    #   {"high": 0.75, "medium": 0.5}  (>= high → HIGH, >= medium → MEDIUM, else LOW)
    band_thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    # Caps keyed by schedule-quality tier, e.g. {"poor": 0.4, "fair": 0.7}.
    # A capped score can never exceed the cap for the insight's quality tier.
    schedule_quality_caps: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # Caps keyed by feed-coverage tier, e.g. {"sparse": 0.5, "partial": 0.8}.
    feed_coverage_caps: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    # Additive bonuses keyed by corroboration signal, e.g.
    #   {"document_backed": 0.1, "cross_feed_agreement": 0.1}
    corroboration_bonuses: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        scope = "global" if self.project_id is None else f"project={self.project_id}"
        return f"<ConfidenceConfig {scope} v{self.version} active={self.active}>"


# ─────────────────────────────────────────────────────────────────────────────
# E5.2 — Locked figures (policy-as-code guard backing store)
# ─────────────────────────────────────────────────────────────────────────────
class LockedFigure(Base):
    """A commercially-sensitive figure that has been locked by a human.

    This is the persistent backing store for the locked-figure guard
    (``locked_guard.py``). Once a figure is locked, the guard rejects any write
    that would change ``value`` — from a recompute, a re-render, or an apply —
    unless the incoming value is byte-identical (idempotent re-writes are
    allowed so single-store re-renders keep working, spec E4.3).

    ``path`` is the canonical, guard-addressable identity of the figure (e.g.
    ``decision.<decision_id>.impact_days``). ``value`` is the canonical string
    serialization used for byte-identical comparison; ``value_hash`` is its
    SHA-256 for cheap tamper detection and audit. ``source_ref`` records the
    owning row (a decision id, a delay_event id) so the lock is traceable.
    """

    __tablename__ = "oe_schedule_intelligence_locked_figure"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_sched_intel_locked_figure_project_path"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Guard-addressable canonical path, unique per project.
    path: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    figure_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Canonical string serialization — the byte-identical comparison target.
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    # SHA-256 of ``value`` for tamper detection / audit trail.
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Ref to the owning row in this or a sibling module (e.g. a decision id).
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # A lock can be released (unlocked) by an authorised actor; we keep the
    # row for audit rather than deleting it. Only ``active`` locks are enforced.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unlocked_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<LockedFigure {self.path}={self.value!r} active={self.active}>"


# ─────────────────────────────────────────────────────────────────────────────
# E1 — Readiness result (Watch)
# ─────────────────────────────────────────────────────────────────────────────
class ReadinessResult(Base):
    """Deterministic Ready/At-risk/Blocked classification of one activity.

    Produced by ``readiness_engine.py`` (Phase 1) from a ``schedule_advanced``
    look-ahead activity + its constraints + CPM float. The activity and its
    binding constraint are referenced by id (``activity_ref`` /
    ``binding_constraint_ref``), never copied.
    """

    __tablename__ = "oe_schedule_intelligence_readiness_result"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Ref to the schedule_advanced look-ahead activity / schedule task.
    activity_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    look_ahead_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    binding_constraint_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    need_by_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_float_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    float_burn_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Drivers behind the classification, each linked to a source row (P4):
    #   [{"type": "constraint", "ref": "...", "detail": "..."}, ...]
    drivers: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")

    # E5.3 confidence attached uniformly.
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    confidence_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence_rationale: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")

    # Stamp of the evaluation run that produced this row (determinism check,
    # E1.1-AC6: two runs over identical inputs produce identical classification).
    evaluation_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<ReadinessResult activity={self.activity_ref} {self.classification}>"


# ─────────────────────────────────────────────────────────────────────────────
# E2 — Forward risk score (Score) + factor decomposition
# ─────────────────────────────────────────────────────────────────────────────
class RiskScore(Base):
    """Deterministic weighted-factor forward-risk composite for one activity.

    Distinct from ``schedule_advanced``'s Monte-Carlo schedule-risk engine:
    this is a forward-looking, decomposable early-warning score (0..1) with a
    band and a first-flagged timestamp. Computed by ``risk_scoring.py`` behind
    a pluggable ``Scorer`` interface (Phase 2). ML is out of MVP (spec §2.3).
    """

    __tablename__ = "oe_schedule_intelligence_risk_score"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Composite score normalised to 0..1.
    score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    band: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scorer_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v0")
    # First time this activity crossed the flag threshold (weeks-early signal).
    first_flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Which confidence_config version priced this score (audit).
    config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    confidence_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence_rationale: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")

    factors: Mapped[list[RiskFactor]] = relationship(
        back_populates="risk_score",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<RiskScore activity={self.activity_ref} score={self.score} band={self.band}>"


class RiskFactor(Base):
    """One decomposed contributor to a :class:`RiskScore` (P4 traceability).

    Every factor links to the concrete source row it was derived from
    (``source_type`` + ``source_ref``) so the UI can reach it in ≤2 clicks.
    """

    __tablename__ = "oe_schedule_intelligence_risk_factor"

    risk_score_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_intelligence_risk_score.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    factor_key: Mapped[str] = mapped_column(String(50), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    raw_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    # weight * normalised(raw_value) — the factor's share of the composite.
    contribution: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Ref to the source row in its owning module (constraint / PO / RFI / snapshot).
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")

    risk_score: Mapped[RiskScore] = relationship(back_populates="factors")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<RiskFactor {self.factor_key} contrib={self.contribution}>"


# ─────────────────────────────────────────────────────────────────────────────
# E4 — Claim-vs-accelerate decision (Quantify → Decide)
# ─────────────────────────────────────────────────────────────────────────────
class Decision(Base):
    """A priced claim-vs-accelerate decision assembled from existing pieces.

    Option A (claim) and Option B (accelerate) are stored as itemised JSON
    (line items each traceable to a source: contract LD/fee, resource rates,
    EAC delta) rather than exploded columns, so the decision surface can render
    both side-by-side without a schema change per new line-item kind. The
    delay event and quantified impact are referenced, not copied. Applying a
    decision is always human-gated through the existing ``app/core`` approval
    gate — this module adds no new gate.
    """

    __tablename__ = "oe_schedule_intelligence_decision"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Ref to the schedule_advanced delay_event this decision responds to.
    delay_event_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Ref to the locked_figure holding the confirmed critical-path impact days.
    impact_locked_figure_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_intelligence_locked_figure.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Itemised, traceable option payloads (see class docstring).
    option_claim: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    option_accelerate: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    recommendation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recommendation_rationale: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)

    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    confidence_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence_rationale: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")

    applied_option: Mapped[str | None] = mapped_column(String(20), nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Decision {self.title[:30]!r} status={self.status}>"
