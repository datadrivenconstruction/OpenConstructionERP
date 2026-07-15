# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Shared enumerations for the Schedule Intelligence module.

These are ``StrEnum`` values used by the pure engines (readiness, risk
scoring, decision, confidence, locked-figure guard) for type-safe code
paths, and persisted as plain ``String`` columns to match the rest of the
codebase (see ``modules/risk/models.py`` — enums are stored as strings,
not DB-level ``ENUM`` types, so SQLite and PostgreSQL behave identically).

Keep the string *values* stable: they are written to the DB and returned
over the API. Renaming a member's value is a data migration.
"""

from __future__ import annotations

from enum import StrEnum


class ReadinessClass(StrEnum):
    """E1 deterministic readiness classification of a look-ahead activity."""

    READY = "ready"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"


class RiskBand(StrEnum):
    """E2 forward-risk band derived from the composite score (0..1)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfidenceBand(StrEnum):
    """E5.3 uniform confidence band attached to every insight."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FactorSourceType(StrEnum):
    """Origin feed of a single risk-score factor (E2 decomposition, P4 trace).

    Every factor must trace back to a concrete source row so the UI can
    reach it in ≤2 clicks. The ``*_ref`` string on the factor row holds the
    id of the source entity in its owning module (never copied here).
    """

    FLOAT = "float"
    CRITICALITY = "criticality"
    CONSTRAINT = "constraint"
    PROCUREMENT = "procurement"
    APPROVAL = "approval"
    RFI = "rfi"
    SLIP_VELOCITY = "slip_velocity"
    HISTORICAL = "historical"
    SNAPSHOT = "snapshot"


class DecisionOption(StrEnum):
    """E4 claim-vs-accelerate options."""

    CLAIM = "claim"
    ACCELERATE = "accelerate"
    MONITOR = "monitor"


class DecisionStatus(StrEnum):
    """Lifecycle of an E4 decision. Apply is always human-gated."""

    DRAFT = "draft"
    RECOMMENDED = "recommended"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"


class LockedFigureType(StrEnum):
    """E5.2 categories of commercially-sensitive figures that get locked.

    Once a figure of one of these types is confirmed by a human, the
    locked-figure guard rejects any subsequent write that would change its
    value from any flow (recompute, re-render, apply). See ``locked_guard``.
    """

    BASELINE_DATE = "baseline_date"
    IMPACT_DAYS = "impact_days"
    ENTITLEMENT_DAYS = "entitlement_days"
    ENTITLEMENT_COST = "entitlement_cost"
    LDS_AVOIDED = "lds_avoided"
    PROLONGATION_COST = "prolongation_cost"
    ACCELERATION_COST = "acceleration_cost"
