# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Comms Intelligence ORM models.

Tables:
    oe_comms_intelligence_analysis - one enrichment verdict per correspondence
    oe_comms_intelligence_draft    - AI/template reply and chase-up drafts

Audit-first, suggestion-only design: an analysis row is pure data ABOUT a
correspondence record - the correspondence row itself is only touched by
the confirm endpoint after a person reviewed the suggestion (house rule:
AI-augmented, human-confirmed). ``raw_response`` is kept per RFC 36 as the
receipt the structured fields were derived from.
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

#: Categories an inbound message can be filed under. ``general`` is the
#: fallback the coercer uses when the model answers off-vocabulary.
ANALYSIS_CATEGORIES = (
    "quote",
    "rfi_response",
    "variation_notice",
    "delay_notice",
    "instruction",
    "claim",
    "approval",
    "delivery",
    "general",
)

#: Review lifecycle of a suggestion. Confirm/dismiss are one-way doors a
#: person walks through; re-analysis resets the row to ``suggested``.
ANALYSIS_STATUSES = ("suggested", "confirmed", "dismissed")

#: What produced the verdict. Heuristics always run; ``ai`` means the LLM
#: pass succeeded and its verdict was merged over the heuristic floor.
ANALYSIS_SOURCES = ("heuristic", "ai")

DRAFT_KINDS = ("reply", "chaser")
DRAFT_STATUSES = ("suggested", "accepted", "dismissed")


class CommsAnalysis(Base):
    """One enrichment verdict for one correspondence record.

    ``correspondence_id`` is unique - re-running analysis updates the row
    in place (status back to ``suggested``) rather than growing an audit
    table per attempt; the previous receipt is replaced because the new
    one supersedes it against the same unchanged source message.
    """

    __tablename__ = "oe_comms_intelligence_analysis"
    __table_args__ = (
        UniqueConstraint(
            "correspondence_id",
            name="uq_oe_comms_intelligence_analysis_correspondence",
        ),
        # Dashboard hot path: unreviewed suggestions per project.
        Index(
            "ix_comms_intel_analysis_project_status",
            "project_id",
            "status",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_comms_intel_analysis_confidence_range",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Plain GUID string rather than an FK: the correspondence table is owned
    # by another module and a deleted letter must not cascade away the audit
    # trail of what the AI once suggested for it (same pattern as
    # clash_ai_triage.subject_id).
    correspondence_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # Denormalised for list rendering without a cross-module JOIN.
    reference_number: Mapped[str] = mapped_column(String(50), nullable=False, default="")

    # ── Verdict ───────────────────────────────────────────────────────────
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Structured facts pulled out of the message. Money amounts are kept
    #: as STRINGS (e.g. "12480.50") - exact, never a float.
    #: Shape: {"prices": [{"amount": str, "currency": str, "context": str}],
    #:         "quote_number": str|None, "reference_numbers": [str],
    #:         "dates": {"response_requested_by": str|None, "event_date": str|None},
    #:         "commitments": [{"who": str, "what": str, "when": str|None}]}
    extracted: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    #: Actions the reviewer may apply to the correspondence row on confirm.
    #: Shape: {"set_status": str|None, "response_required_by": str|None,
    #:         "link_rfi_id": str|None, "correspondence_type": str|None}
    suggestions: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    reply_needed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    # ── Review lifecycle ──────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="suggested", server_default="suggested", index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Which suggestion keys the reviewer actually applied on confirm - the
    #: receipt that distinguishes "confirmed everything" from a partial apply.
    applied: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )

    # ── Provenance / audit ────────────────────────────────────────────────
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="heuristic", server_default="heuristic")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1.0", server_default="v1.0")
    raw_response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cost_usd_estimate: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0.0, server_default="0.0")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<CommsAnalysis {self.reference_number or self.correspondence_id} "
            f"cat={self.category} conf={self.confidence:.2f} {self.status}>"
        )


class CommsDraft(Base):
    """A suggested reply or chase-up for one correspondence record.

    Drafts are text a person copies into their mail client (or edits and
    discards) - this module never sends anything itself, so accepting a
    draft has no side effect beyond recording that it was used.
    """

    __tablename__ = "oe_comms_intelligence_draft"
    __table_args__ = (
        Index(
            "ix_comms_intel_draft_correspondence_created",
            "correspondence_id",
            "created_at",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    correspondence_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="reply")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    #: 0.0 for template fallbacks; the model's own estimate for AI drafts.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="suggested", server_default="suggested")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="template", server_default="template")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<CommsDraft {self.kind} for {self.correspondence_id} ({self.status})>"
