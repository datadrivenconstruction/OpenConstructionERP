# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Public funding ORM models.

Tables (all prefixed ``oe_funding_``):
    programme        -- what a funding body offers, and on what terms
    application      -- one project asking one programme, plus its award
    disbursement     -- drawing part of an awarded amount
    proof_of_use     -- the after-the-fact account of where the money went
    obligation       -- a dated thing the award makes someone answerable for
    cost_allocation  -- which project costs the programme will count

Dates are ISO-8601 strings in ``String(40)`` columns, which is what the rest
of the project does for business dates. The reason is worth stating once: a
funding deadline is a calendar day decided by an authority in its own
timezone, not an instant, and storing it as a timestamp invites a conversion
that can move a deadline across midnight. ``created_at`` and ``updated_at``
are real timestamps and come from ``Base``.

Money is ``MoneyType``, which is Decimal in Python and exact in the database.
Several columns here are the difference between two other columns, and a
float would make the difference wrong in the last cent exactly where an
auditor looks.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base


class FundingProgramme(Base):
    """A programme a funding body offers, with the terms it imposes.

    This is reference data, shared across the projects of a tenant. Most rows
    arrive from a Country Pack rather than being typed in, which is why the
    national specifics live in columns rather than in code: a German KfW
    programme and a United States formula grant differ in the numbers below,
    not in which numbers exist.
    """

    __tablename__ = "oe_funding_programme"
    __table_args__ = (
        UniqueConstraint("code", "country", name="uq_oe_funding_programme_code_country"),
        Index("ix_oe_funding_programme_country_status", "country", "status"),
    )

    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Who offers it ────────────────────────────────────────────────────
    authority_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # supranational | national | regional | municipal. The level matters for
    # cumulation: money from two levels usually combines, money from two
    # programmes of the same body usually does not.
    authority_level: Mapped[str] = mapped_column(String(40), nullable=False, default="national")
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="", index=True)
    # Subdivision code for a regional programme: a German Land, a United
    # States state, a Spanish comunidad. Empty for a national programme.
    region_code: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    # ── What it gives ────────────────────────────────────────────────────
    # grant | loan | repayment_grant | guarantee | tax_relief | equity.
    # ``repayment_grant`` is a loan whose principal is partly forgiven on
    # completion, which several German programmes use and which is neither a
    # grant nor a plain loan for reporting.
    instrument: Mapped[str] = mapped_column(String(40), nullable=False, default="grant")
    funding_rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0"))
    min_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    max_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    # ── What it demands ──────────────────────────────────────────────────
    # The share of eligible costs the applicant must carry itself. Not simply
    # 100 minus the funding rate: a programme can fund 40 percent, require an
    # own share of 20, and leave the remaining 40 to other sources.
    own_share_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0"))
    # Ceiling on everything public added together, expressed as a share of
    # eligible costs. In the European Union this is the state-aid intensity;
    # elsewhere it is a cumulation cap written into the programme. Zero means
    # the programme declares none.
    aid_intensity_cap_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0"))
    de_minimis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cumulative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The single most expensive mistake in public funding, and the reason it
    # is a column rather than a note: in most programmes, work begun before
    # the application was filed is not fundable at all, and no later approval
    # repairs it. German practice calls it the Verbot des vorzeitigen
    # Maßnahmenbeginns; United States practice calls the same thing pre-award
    # costs. A few programmes genuinely allow it, hence the flag.
    requires_application_before_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── When ─────────────────────────────────────────────────────────────
    application_window_start: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    application_window_end: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    rolling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Days after the award period ends within which the proof of use is due.
    # German general conditions say six months; several EU programmes say
    # ninety days. Zero means the programme sets no standing deadline and the
    # date comes from the award notice instead.
    proof_of_use_due_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Days within which money received must actually be spent. German general
    # conditions say two months, and missing it turns into an interest claim
    # rather than a warning, which is why it generates its own obligation.
    disbursement_spend_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Years the vouchers must be kept after the proof of use is accepted.
    retention_years: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Who and what qualifies ───────────────────────────────────────────
    eligible_applicant_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    eligible_cost_categories: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    excluded_cost_categories: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # draft | open | closed | suspended
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open", index=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # The day a human last checked the terms above against the source. A
    # programme catalogue with no such date is read as current forever, and
    # funding terms change every budget year.
    last_verified_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # Which Country Pack supplied this row, empty when a user typed it in.
    # Rows owned by a pack are replaced on pack update; typed rows are not.
    pack_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    applications: Mapped[list["FundingApplication"]] = relationship(
        back_populates="programme",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )


class FundingApplication(Base):
    """One project asking one programme, and the answer it received.

    The award fields are filled from the notice that comes back. They are on
    the application rather than in a table of their own because an
    application has exactly one decision, and splitting them would let a
    project hold an approved amount with no application behind it.
    """

    __tablename__ = "oe_funding_application"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_funding_application_project_code"),
        # The name is the platform's, not a choice. ``app.core.pg_optimizations``
        # gives every table carrying both columns a ``(project_id, status)``
        # index on ``after_create`` and skips its own only when an index of
        # that exact name is already declared. Naming it anything else leaves
        # the table with two identical indexes, paid for on every write.
        Index("ix_oe_funding_application_project_id_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    programme_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_funding_programme.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    applicant_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    applicant_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    # draft | submitted | in_review | approved | rejected | withdrawn | closed
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)

    # ── What was asked for ───────────────────────────────────────────────
    eligible_cost_base: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    requested_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    own_share_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    submitted_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    decision_expected_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    decided_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    # ── What came back ───────────────────────────────────────────────────
    award_reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    approved_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    # The window inside which costs must fall to be claimable. Everything the
    # module later checks about a cost date is checked against this pair.
    award_period_start: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    award_period_end: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Facts about the work itself ──────────────────────────────────────
    measure_start_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # Set only when the authority granted permission to begin early, in
    # writing. It exists so the validation rule can be told the truth rather
    # than be switched off.
    early_start_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    early_start_reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    responsible_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Soft links, plain UUIDs with no database foreign key, so the funding
    # module stays installable without the modules it can point at.
    linked_estimate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    linked_schedule_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    programme: Mapped["FundingProgramme"] = relationship(
        back_populates="applications",
        lazy="raise_on_sql",
    )
    disbursements: Mapped[list["FundingDisbursement"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    proofs_of_use: Mapped[list["FundingProofOfUse"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    obligations: Mapped[list["FundingObligation"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    cost_allocations: Mapped[list["FundingCostAllocation"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )


class FundingDisbursement(Base):
    """A request to draw part of an awarded amount against real spending."""

    __tablename__ = "oe_funding_disbursement"
    __table_args__ = (
        UniqueConstraint("application_id", "sequence", name="uq_oe_funding_disbursement_app_sequence"),
        Index("ix_oe_funding_disbursement_app_status", "application_id", "status"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_funding_application.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    code: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    # The spending window this draw covers. Checked against the award period,
    # because a draw for costs dated outside it is the second most common way
    # a grant is clawed back.
    period_from: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    period_to: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    requested_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    approved_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    received_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # Derived from the programme's spend window once money is received, and
    # kept as a column rather than recomputed, because the programme's terms
    # can change after the fact and this deadline must not move with them.
    spend_deadline_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    amount_requested: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    amount_approved: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    amount_received: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))

    # draft | submitted | approved | paid | rejected
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    # Soft links to invoicing records that make up this draw.
    invoice_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    application: Mapped["FundingApplication"] = relationship(
        back_populates="disbursements",
        lazy="raise_on_sql",
    )


class FundingProofOfUse(Base):
    """The account of where the money went, interim or final."""

    __tablename__ = "oe_funding_proof_of_use"
    __table_args__ = (Index("ix_oe_funding_proof_app_status", "application_id", "status"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_funding_application.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # interim | final
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="final")
    due_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    submitted_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    accepted_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # pending | drafting | submitted | accepted | rejected
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)

    # Every jurisdiction asks for the same two halves under different names:
    # a narrative saying what was achieved, and a numeric statement saying
    # what it cost. German practice calls them Sachbericht and zahlenmäßiger
    # Nachweis; the United States federal financial report splits the same
    # way. Keeping them as two fields means a Country Pack changes the form,
    # not the model.
    narrative_report: Mapped[str] = mapped_column(Text, nullable=False, default="")
    total_eligible_spent: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    total_funding_used: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    total_own_share: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    voucher_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    findings: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The day the vouchers may finally be thrown away. Computed from the
    # programme's retention period when the report is accepted.
    retention_until: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    application: Mapped["FundingApplication"] = relationship(
        back_populates="proofs_of_use",
        lazy="raise_on_sql",
    )


class FundingObligation(Base):
    """A dated thing the award makes somebody answerable for.

    Deadlines arrive from three different places and a reader has to be able
    to tell them apart, because they can be argued with to different degrees.
    A programme rule is the same for everyone. A condition in an award notice
    was written for this applicant. A manual entry is somebody's own note.
    """

    __tablename__ = "oe_funding_obligation"
    __table_args__ = (
        Index("ix_oe_funding_obligation_due", "due_on", "status"),
        Index("ix_oe_funding_obligation_app_kind", "application_id", "kind"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_funding_application.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # application_deadline | measure_start | disbursement | spend_window |
    # interim_report | final_report | retention_end | condition
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="condition")
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # What ``detail`` says, in a form that survives translation: the message
    # key and the values it interpolates. ``detail`` itself is English prose
    # rendered from these two, and is a convenience rather than the source of
    # truth. Both are written when the obligation is derived, not worked out
    # when it is read, for the same reason ``due_on`` is: editing a
    # programme's terms must not silently reword a deadline that has already
    # been sent to somebody. Empty on an obligation a person typed, whose
    # words are their own and are not a key into anything.
    detail_key: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # ``server_default`` is not decoration here, it is the only thing that
    # makes this column arrive correctly on an install whose schema moved at
    # boot. The heal writes a DDL default only when it can spell the model
    # default as a literal, and ``default=dict`` is a callable the ORM runs
    # per row, which has no spelling - so without the line below the column
    # lands nullable with no default and the schema disagrees with this file
    # for the life of the install. The literal is the same one
    # ``v41_funding_obligation_detail`` writes, so the two build paths cannot
    # end up declaring different defaults. It is spelled as a plain string
    # rather than as ``text("'{}'")`` because the heal renders a string default
    # by quoting it and renders an expression by compiling it inside a bare
    # ``except Exception`` that falls back to emitting no default at all. Both
    # spellings produce ``DEFAULT '{}'``; only one of them has no silent way to
    # produce nothing.
    detail_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    due_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # programme_rule | award_notice | manual
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    # Where the obligation is written down, so a reader can go and check it:
    # a clause number in the general conditions, a paragraph of the notice.
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    responsible_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # open | done | waived. Overdue is not stored: it is "open and the due
    # date has passed", and storing it would need a job to keep it true.
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open", index=True)
    completed_on: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    application: Mapped["FundingApplication"] = relationship(
        back_populates="obligations",
        lazy="raise_on_sql",
    )


class FundingCostAllocation(Base):
    """Which of the project's costs this programme will actually count.

    The gap between what a project costs and what a programme funds is where
    applications go wrong, and it is not a percentage. A programme names
    categories, and the same building carries costs inside and outside them.
    One row here is one cost group with a decision attached and a reason.
    """

    __tablename__ = "oe_funding_cost_allocation"
    __table_args__ = (Index("ix_oe_funding_alloc_app_eligibility", "application_id", "eligibility"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_funding_application.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The cost code in whatever classification the project uses: a DIN 276
    # group in Germany, an RICS element in the United Kingdom, a CSI division
    # in North America. Stored as written rather than mapped, because a
    # funding body reads the applicant's own classification back to them.
    cost_group: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    # What survives the programme's rules. Not derived from a percentage:
    # partial eligibility is usually a named carve-out, not a ratio.
    eligible_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=Decimal("0"))
    # eligible | partially_eligible | not_eligible | undecided
    eligibility: Mapped[str] = mapped_column(String(30), nullable=False, default="undecided")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # estimate | boq | invoice | manual
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    source_ref_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    application: Mapped["FundingApplication"] = relationship(
        back_populates="cost_allocations",
        lazy="raise_on_sql",
    )
