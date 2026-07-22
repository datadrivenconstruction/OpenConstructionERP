# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Takeoff ORM models.

Tables:
    oe_takeoff_document        - uploaded PDF documents for quantity takeoff
    oe_takeoff_measurement     - measurement annotations (distance, area, count, etc.)
    oe_takeoff_cad_session     - persistent CAD extraction sessions (replaces in-memory cache)
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# Numeric precision for measured-quantity columns on TakeoffMeasurement.
# Round-6 audit (2026-05-22) flagged ``measurement_value``, ``depth``,
# ``volume``, ``perimeter`` as ``Float`` even though every one of them
# flows directly into BOQ totals via ``link-to-boq``. The sibling
# ``dwg_takeoff.DwgAnnotation`` already uses Numeric(18, 6) (Round 3
# Wave A migration ``v3097_dwg_takeoff_decimal_quantities``); this
# brings the PDF takeoff path into the same precision regime so that
# a measurement carrying through to a unit_rate × quantity computation
# stays within ±1e-6 of the user-visible value instead of accumulating
# binary float drift across the round-trip.
_MEASURE_NUMERIC = Numeric(18, 6)
_SCALE_NUMERIC = Numeric(18, 6)


class CadExtractionSession(Base):
    """Persistent storage for CAD file extraction sessions.

    Replaces the in-memory ``_cad_sessions`` dict to survive server restarts
    and support multi-process deployments.  Sessions expire after 24 hours.
    """

    __tablename__ = "oe_takeoff_cad_session"

    session_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), default="")
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)  # rvt, ifc, dwg, dgn
    element_count: Mapped[int] = mapped_column(Integer, default=0)
    extraction_time: Mapped[float] = mapped_column(Float, default=0)
    elements_data: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    columns_metadata: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    project_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_permanent: Mapped[bool] = mapped_column(default=False, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="")

    # Phase 17: session lifetime & BIM linkage
    session_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=7)
    is_persistent: Mapped[bool] = mapped_column(default=False, server_default="0")
    bim_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)

    def __repr__(self) -> str:
        return f"<CadExtractionSession {self.session_id} ({self.filename})>"


class TakeoffDocument(Base):
    """Uploaded PDF document for quantity takeoff."""

    __tablename__ = "oe_takeoff_document"
    __table_args__ = (
        # One takeoff document per (project, source Project-Files document).
        # POST /documents/from-source find-or-creates by (project_id,
        # source_document_id): it does an unlocked SELECT then INSERT, so two
        # concurrent opens of the same source PDF could both miss and both
        # insert, minting duplicate rows that strand measurements on an
        # unreachable document id (issue #369). This unique index is the
        # database-level guard - the losing INSERT raises IntegrityError and the
        # service resolves to the winning row. source_document_id is NULL for
        # direct uploads, and PostgreSQL treats NULLs as distinct in a unique
        # index, so ordinary uploads never collide; the constraint only ever
        # binds the from-source rows that carry a non-NULL source id. Kept a
        # plain (non-partial) unique index on purpose so the startup
        # postgres_auto_migrate heal, which reconstructs plain indexes but skips
        # partial/expression ones, materialises it on already-provisioned
        # embedded and external databases too.
        Index(
            "uq_takeoff_document_project_source",
            "project_id",
            "source_document_id",
            unique=True,
        ),
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/pdf")
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="uploaded"
    )  # uploaded | analyzing | analyzed | error
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Path to the stored PDF file on disk (for viewing/download)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True, default=None)
    # Originating Project-Files document id (oe_documents_document PK) when this
    # takeoff document was created by opening a file from the Documents hub. NULL
    # for direct uploads. This is the idempotency key for the find-or-create in
    # ``POST /documents/from-source/{id}``: opening the same Project-Files PDF
    # twice reuses this row instead of minting a duplicate and re-parsing. Kept
    # as a String(36) uuid (the established uuid-as-string pattern in this
    # module) and indexed for the once-per-open lookup. Additive + nullable, so
    # every existing row reads unchanged; create_all + postgres_auto_migrate add
    # the column on normal deploys and the alembic migration keeps the revision
    # graph and any external/migration-driven DB consistent.
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True, default=None)
    # Extracted text content from PDF (plain text for AI analysis)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Per-page data: [{ page: 1, text: "...", tables: [...] }, ...]
    page_data: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Analysis results from AI
    analysis: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # Per-page scale calibration (issue #334). The document-level, authoritative
    # source of truth for each sheet's drawing scale, mirroring the frontend
    # ``PageScales`` shape ({defaultScale, byPage}). Calibration used to live
    # only in the browser (localStorage) plus a weak per-measurement echo, so a
    # reload where a stale local default won - or a non-geometry edit that
    # re-stamped the live view scale - silently dropped a real calibration.
    # Persisting it once here makes it durable across reloads and devices, with
    # the per-measurement ``scale_pixels_per_unit`` kept as capture provenance
    # only. Nullable with no server_default: NULL = never calibrated at the
    # document level (fall back to the legacy per-measurement stamps), so every
    # existing row reads unchanged and no backfill is needed. create_all +
    # postgres_auto_migrate add the column on normal deploys, and migration
    # v3239_takeoff_page_scales keeps the revision graph and any external /
    # migration-driven DB consistent.
    page_scales: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True, default=None
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<TakeoffDocument {self.filename} ({self.status})>"


class TakeoffMeasurement(Base):
    """Measurement annotation created during quantity takeoff.

    Stores geometric measurements (distance, area, count, polyline, volume)
    drawn on PDF pages, with optional links to BOQ positions and scale info.
    """

    __tablename__ = "oe_takeoff_measurement"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # distance, area, count, polyline, volume
    group_name: Mapped[str] = mapped_column(String(100), nullable=False, default="General")
    group_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3B82F6")
    annotation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    points: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )  # [{x, y}, ...]
    # Round-6 audit (2026-05-22) - these four columns feed BOQ totals.
    # Migrated Float → Numeric(18, 6) so PDF takeoff matches the dwg_takeoff
    # precision regime (v3097_dwg_takeoff_decimal_quantities).
    measurement_value: Mapped[Decimal | None] = mapped_column(_MEASURE_NUMERIC, nullable=True)
    measurement_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="m")
    depth: Mapped[Decimal | None] = mapped_column(_MEASURE_NUMERIC, nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(_MEASURE_NUMERIC, nullable=True)
    perimeter: Mapped[Decimal | None] = mapped_column(_MEASURE_NUMERIC, nullable=True)
    count_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Opening deduction (void / cut-out). When true this area measurement
    # represents an opening (door, window, recess) that must be SUBTRACTED
    # from the gross area of its group, so a net area = gross - openings.
    # ``measurement_value`` is still stored as a positive gross area (the
    # shoelace recompute is sign-agnostic); the subtraction lives in the
    # rollup, and ``_pick_takeoff_value`` refuses to push a lone deduction
    # into a BOQ position so a void can never masquerade as a gross quantity.
    # Additive with a server_default so every existing row reads as a normal
    # (non-deduction) measurement.
    is_deduction: Mapped[bool] = mapped_column(default=False, server_default="0", nullable=False)
    # ``scale_pixels_per_unit`` stays Float - it's a UI calibration ratio
    # (px-per-metre) used as a divisor and never persisted into a money
    # rollup. Migrating it would force every existing PDF takeoff session
    # in production to be re-calibrated for no precision gain.
    scale_pixels_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    linked_boq_position_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ── Vision-LLM plan reading (issue #194) ───────────────────────────────
    # Provenance and review state. All three are additive with a server_default
    # so every existing row reads unchanged. A plan-read proposal lands as
    # ``source='ai_plan_read'`` / ``review_status='proposed'`` with the model
    # confidence; manual draws stay ``manual`` / ``confirmed`` (back-compat).
    # ``confidence`` is NULL for non-AI rows (NULL = honestly not AI-derived,
    # never a fake 0.0). The run id is stamped into ``metadata_`` so no FK
    # column is needed and cascade stays clean.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )  # manual | ai_plan_read | ai_takeoff | cad_import | gaeb_import
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="confirmed", server_default="confirmed"
    )  # proposed | confirmed | rejected
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_takeoff_measurement_confidence_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<TakeoffMeasurement {self.type} group={self.group_name} page={self.page}>"


class AiTakeoffRun(Base):
    """One vision-LLM plan-read run - the pollable job bookkeeping row.

    Mirrors the proven ``AiEstimatorRun`` / ``AIEstimateJob`` shape. The run is
    a long-lived, pollable job; ``status`` is the FSM
    ``queued -> rasterizing -> reading -> validating -> review ->
    applied | failed | cancelled``. The vision call is bring-your-own-key per
    the confirming user, and a hard cost cap (``TAKEOFF_AI_MAX_COST_USD``) is
    enforced pre-flight and rolled up per user from the windowed sum of these
    rows' ``cost_usd_estimate`` so one tenant cannot exhaust another's budget.
    """

    __tablename__ = "oe_ai_takeoff_run"
    __table_args__ = (
        Index("ix_ai_takeoff_run_project", "project_id"),
        Index("ix_ai_takeoff_run_project_status", "project_id", "status"),
        Index("ix_ai_takeoff_run_user", "user_id"),
        Index("ix_ai_takeoff_run_user_created", "user_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # scale | rooms | symbols | full
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="rooms", server_default="rooms")
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # FSM: queued | rasterizing | reading | validating | review | applied |
    # failed | cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", server_default="queued")
    scale_pixels_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    do_cost_match: Mapped[bool] = mapped_column(default=False, server_default="0")
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(120), nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<AiTakeoffRun {self.status} mode={self.mode} page={self.page}>"
