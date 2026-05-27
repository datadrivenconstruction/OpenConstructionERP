# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍ORM models for the clash AI triage module.

Tables:
    oe_clash_triage_result — one LLM triage verdict for a clash subject.

Audit-first design: the full ``raw_prompt`` and ``raw_response`` are
persisted alongside the structured verdict so a reviewer can always
trace why the LLM said what it said. The same ``(subject_id,
prompt_version, model_name)`` triple is the cache key — calling triage
twice with the same prompt against the same clash returns the persisted
row, no fresh LLM call.

Subject polymorphism: a triage targets either a ``ClashResult`` (the
run-scoped row, ``subject_type="clash"``) or a ``ClashIssue`` (the
persistent identity across re-runs, ``subject_type="clash_issue"``). We
deliberately store the foreign key as a plain GUID column rather than
two FKs — the sibling ``ClashIssue`` table is owned by another agent and
may be missing on dev DBs that pre-date its migration; the service layer
degrades to ``subject_type="clash"`` in that case.
"""

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ClashTriageResult(Base):
    """‌⁠‍A persisted LLM triage verdict for one clash subject.

    ``subject_type`` + ``subject_id`` form the polymorphic link to either
    a ``ClashResult`` (per-run row) or a ``ClashIssue`` (cross-run
    identity). The cache key on the service layer is
    ``(subject_id, prompt_version, model_name)`` so two re-runs against
    the same prompt + model resolve from the row instead of paying for
    another LLM call. ``force_refresh=True`` writes a fresh row.

    ``raw_prompt`` and ``raw_response`` are kept for audit. They are the
    SINGLE source of truth when a coordinator disputes a verdict — the
    structured fields are derived from ``raw_response``, not from the
    other way around.
    """

    __tablename__ = "oe_clash_triage_result"
    __table_args__ = (
        # Cache lookup hot path: same clash + same prompt + same model.
        Index(
            "ix_clash_triage_subject_prompt_model",
            "subject_id",
            "prompt_version",
            "model_name",
        ),
        # History endpoint hot path: per-subject newest-first.
        Index("ix_clash_triage_subject_created", "subject_id", "created_at"),
        # Confidence must be a probability in [0, 1] — guards against a
        # bad LLM response slipping past schema validation.
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_clash_triage_confidence_range",
        ),
    )

    # ── Polymorphic subject link ──────────────────────────────────────────
    # ``"clash"`` → ``oe_clash_result.id``;
    # ``"clash_issue"`` → ``oe_clash_issue.id`` when that table is present.
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False, default="clash", server_default="clash")
    subject_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # Convenience column — the original clash_id even when the triage was
    # later promoted to a clash_issue subject. NULL on issue-only triages
    # where the clash row is no longer reachable. Lets the history endpoint
    # answer "show triages for clash X" without a runtime polymorphic JOIN.
    clash_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)

    # ── LLM call metadata ─────────────────────────────────────────────────
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1.0", server_default="v1.0")

    # ── Structured verdict ────────────────────────────────────────────────
    # One of: real_design_flaw | expected_intersection | tolerance_artifact
    #       | modeling_error | duplicate | unclear
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="unclear")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    # critical | high | medium | low — independent suggestion (the user's
    # confirmed severity stays on ``ClashResult.severity``).
    severity_suggested: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium", server_default="medium"
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # reroute_pipe | add_sleeve | accept_intersection | ignore_duplicate
    # | escalate_to_designer | request_more_info — NULL for ``unclear``.
    suggested_action: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # List of ``"key=value"`` strings the LLM said it leaned on.
    model_evidence_used: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )

    # ── Audit trail ───────────────────────────────────────────────────────
    raw_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Per-call USD cost estimate (input + output tokens × per-1k rate).
    # Always positive, ``Numeric(10, 4)`` so a single triage cannot exceed
    # $999999.9999 (sanity rather than reality).
    cost_usd_estimate: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0.0, server_default="0.0")

    # ── Provenance ────────────────────────────────────────────────────────
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<ClashTriageResult subject={self.subject_type}:{self.subject_id} "
            f"cat={self.category} conf={self.confidence:.2f}>"
        )
