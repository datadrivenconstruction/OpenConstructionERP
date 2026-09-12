# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate-basis ORM models.

Tables:
    oe_estimate_basis_document - one drafted, editable basis-of-estimate per
        generation, scoped to a project (and optionally the BOQ it was drawn
        from). The three qualification lists and the coverage snapshot are held
        as JSON so a regenerate or a user edit is a single-row write.
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class EstimateBasis(Base):
    """A drafted basis-of-estimate (inclusions, exclusions, assumptions).

    Columns:
        project_id - owning project (CASCADE on delete).
        boq_id - the BOQ the basis was generated from, when a single BOQ was
            targeted; ``None`` means it spans every BOQ of the project. Kept as a
            bare indexed GUID (no hard FK) so deleting a BOQ never cascades away
            the client-facing document.
        title - human-readable heading for the document.
        status - ``draft`` while being edited, ``final`` once signed off.
        inclusions / exclusions / assumptions - JSON lists of qualification
            dicts (see :class:`.derivation.Qualification`); each item carries a
            stable id, its text, the trade it derives from and an enabled flag,
            so the UI edits, reorders and toggles lines without losing identity.
        coverage - JSON snapshot of the present/absent trade picture and quality
            flags at generation time, so the export shows the basis even after
            the source estimate moves on.
        currency / financials / provenance / pricing_date - the derived half of
            the document: the money it qualifies, where its lines came from, and
            the date its rates are current to. All snapshots, for the same
            reason ``coverage`` is one.
        estimate_class / accuracy_low_pct / accuracy_high_pct /
            market_conditions / contingency_rationale - the human half. The
            platform suggests a class from the evidence; only an estimator
            stores one.
        generated_at - ISO-8601 UTC timestamp of the derivation.
        created_by - the user who generated the document (provenance).
        metadata_ - module-extensible blob.
    """

    __tablename__ = "oe_estimate_basis_document"
    __table_args__ = (
        # The list endpoint reads a project's documents newest-first.
        Index("ix_estimate_basis_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Basis of estimate")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )

    inclusions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    exclusions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    assumptions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    coverage: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    generated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    # ── The number the document qualifies ────────────────────────────────
    # A basis of estimate that does not carry the estimate's own figure makes
    # the reader open a second screen to learn what is being qualified, and
    # leaves the exported document unreadable on its own. ``financials`` is the
    # money snapshot taken at generation time (direct cost, markups, grand
    # total, and the two "this total is not final" flags the BOQ roll-up
    # raises); ``currency`` is resolved from the project when the caller does
    # not state one, so the figures on screen carry a symbol.
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="", server_default="")
    financials: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Where the estimate's lines came from - the source families, the
    # machine-proposed lines and their confidence, and the model bindings that
    # have drifted. Derived, never typed. Also carries the class SUGGESTION and
    # its evidence, which is a proposal and not the decision below.
    provenance: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # The date the priced rates are current to, derived from the freshest cost
    # item actually applied or the bill's stated base date.
    pricing_date: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ── Human judgement ──────────────────────────────────────────────────
    # The estimate class is an AACE 18R-97 class 1-5 (lower is more defined),
    # the same 1-5 space the BOQ module's classification endpoint returns.
    # NULL means "not stated yet": the platform suggests a class from the
    # evidence but never writes one on the estimator's behalf, so an unanswered
    # document reads as unanswered rather than as a machine's opinion.
    estimate_class: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Signed accuracy bounds as percentages, Decimal-as-string (e.g. "-20" /
    # "30"). Seeded from the chosen class's published range and editable, since
    # a house may run tighter or wider bands than the standard's.
    accuracy_low_pct: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    accuracy_high_pct: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    # The two judgements no derivation can make: what the market was doing when
    # the estimate was priced, and why the contingency is the size it is.
    market_conditions: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    contingency_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # OC-03: the client's stated budget target, separate from the calculated
    # estimate. A basis that shows only a calculated figure on a concept-stage
    # project tells the reader nothing about what the client asked for. This JSON
    # carries type ("client_target" / "budget" / "tender" / "contract"), amount,
    # currency, gross_net mode, contingency handling and source/date, so a
    # reviewer can see the two numbers side by side without hunting through notes.
    budget_target: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
        default=None,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EstimateBasis project={self.project_id} status={self.status} title={self.title!r}>"
