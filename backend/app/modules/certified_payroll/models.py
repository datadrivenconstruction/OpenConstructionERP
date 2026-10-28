# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Certified payroll ORM models.

Tables:
    oe_certpay_determination  - a wage determination the contractor has on file
    oe_certpay_classification - one craft line inside a determination, carrying
                                the basic hourly rate and the fringe rate apart
    oe_certpay_assignment     - which classification a worker works under on a
                                project, over a validity window
    oe_certpay_week           - one week's certified payroll: the statement of
                                compliance, the signature and the fringe election
    oe_certpay_line           - the frozen, per-worker record of a certified week

Who owns what, and where the join is
====================================

``oe_payroll`` owns the pay run. ``oe_certified_payroll`` owns the compliance
record. They are joined, not parallel, and neither is a copy of the other:

    oe_payroll               oe_certified_payroll
    ----------               --------------------
    PayrollBatch             WageDetermination
    PayrollEntry             WageClassification
    PayrollDeduction         WorkerClassificationAssignment
    (oe_payroll_*)           CertifiedPayrollWeek
                             CertifiedPayrollLine
                             (oe_certpay_*)

The pay run answers "what did we pay this person, and when". The compliance
record answers "what were we required to pay them, on whose authority, and did
we say so in writing". Neither question is derivable from the other: a rate on
its own does not say which determination it had to meet, and a determination on
its own does not say what anybody worked.

The join runs one way only. This module reads ``PayrollEntry`` (hours, rate,
work date), ``PayrollBatch`` (project, currency) and ``PayrollDeduction``, and
it uses ``payroll.intl`` for the money arithmetic so there is one implementation
of overtime in the tree. It writes nothing back, declares no relationship or
foreign key onto any ``oe_payroll_*`` table, and links to a worker through a
soft ``resource_id`` column that mirrors ``PayrollEntry.resource_id`` without
constraining it. Deleting this module leaves the pay run untouched.

This split is worth stating because it is not obvious from the names, and both
the author of this module and its reviewer independently started from the
assumption that a certified payroll must be a second payroll. It is not. It is
a statement about a pay run that already happened.

What this module is NOT
=======================

It is not a second payroll. ``oe_payroll`` already aggregates field hours into
``PayrollBatch`` / ``PayrollEntry`` / ``PayrollDeduction`` per worker per day,
and that stays the one live payroll model. The weekly form is a pivot of those
rows: one line per worker per classification, with the hours spread across the
seven days of the week. Before a week is certified there are no rows in
``oe_certpay_line`` at all - the service derives the week live from the payroll
entries, so there is never a second live copy of the same hours to drift.

``oe_certpay_line`` exists only from the moment somebody signs. A certified
payroll is a legal record submitted to an awarding body: it has to say what was
certified, not what the payroll happens to say today. So certification freezes
the derived rows into real columns, denormalising the classification title, the
determination identifier and both required rates alongside them. Renaming a
classification next month must not silently rewrite a statement somebody signed
last month.

Basic and fringe are held apart, everywhere
===========================================

A prevailing wage is a basic hourly rate plus a fringe benefit rate, and the
contractor may discharge the fringe into a bona fide plan or pay it in cash.
Overtime is computed on the basic rate alone, never on basic plus fringe.
Folding the two into one number is the single most common certified payroll
error, and it is not a mistake this schema can express: there is no column
anywhere holding a combined prevailing rate. ``required_basic_rate`` and
``required_fringe_rate`` come from the determination; ``paid_basic_rate`` and
``paid_fringe_rate`` are what the contractor asserts it actually paid; the
election between plan and cash is its own column, because the statement of
compliance has to state it per worker and a single blended rate cannot.

No rate table ships
===================

Wage determinations are per craft, per county, per awarding body, and they are
reissued on a schedule this repository cannot track. Nothing here is seeded.
A determination row is what the contractor received from the awarding body and
typed in, and it carries where it came from (``authority``, ``identifier``,
``decision_date``, ``source_note``) so the record says which document fixed the
rate. The rates live on the classification because the record has to reproduce
what was certified years later; that is a historical record of one document,
not a shipped schedule of what any craft earns anywhere.

Money is Decimal-as-string, matching ``oe_payroll``. Dates are ISO YYYY-MM-DD
strings for the same reason: these rows are read back verbatim into a form.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# Who issued the determination. Three values, not two, and the third is load
# bearing: Texas has no state wage-determination body at all, so the awarding
# public body sets the rate itself, either by surveying local wages or by
# adopting the federal determination for the locality (Government Code
# 2258.022(a)). A federal-or-state pair cannot express that, and a Texas job is
# the common case, not the exotic one.
ALL_DETERMINATION_AUTHORITIES: tuple[str, ...] = ("federal", "state", "awarding_body")

# How the awarding body arrived at the rate. Mirrors the ``methods`` vocabulary
# already carried by ``us_tx_pack``, plus the ordinary case of a published
# schedule (a state body that issues its own, as California does).
ALL_DETERMINATION_METHODS: tuple[str, ...] = (
    "published_schedule",
    "local_wage_survey",
    "federal_locality_determination",
)

# How the fringe was discharged for one worker in one week. ``plan`` is payment
# into a bona fide fringe benefit plan, ``cash`` is payment of the fringe
# directly in the worker's wages, ``mixed`` is part to a plan and the remainder
# in cash. The statement of compliance elects between these, so it is a column.
ALL_FRINGE_ELECTIONS: tuple[str, ...] = ("plan", "cash", "mixed")

# Week lifecycle. Two states only: a week is being prepared, or somebody has
# signed it. There is no "submitted" middle state, because the signature IS the
# submission-worthy act and a signed statement of compliance is not editable.
ALL_WEEK_STATUSES: tuple[str, ...] = ("draft", "certified")


class WageDetermination(Base):
    """A wage determination the contractor holds for one project.

    A referenced document, not a number copied onto a worker. The row records
    which body issued it, under what identifier, on what date, and by what
    method, so the payroll can always say which determination fixed a rate and
    why that one governed.

    ``locked`` turns True the moment a certified week cites this determination.
    A locked determination and its classifications are immutable: the figures a
    signed statement of compliance rests on cannot be edited afterwards.
    """

    __tablename__ = "oe_certpay_determination"
    __table_args__ = (
        Index("ix_oe_certpay_determination_project_authority", "project_id", "authority"),
        UniqueConstraint("project_id", "authority", "identifier", name="uq_oe_certpay_determination_project_ident"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # federal | state | awarding_body - see ALL_DETERMINATION_AUTHORITIES.
    authority: Mapped[str] = mapped_column(String(20), nullable=False, default="federal", server_default="federal")
    # The issuing body in words, e.g. "State Department of Industrial Relations"
    # or the name of the awarding city. Free text: naming every awarding body in
    # the United States is not something this repository can or should attempt.
    authority_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # ISO 3166-2 where one applies ("US" federal, "US-CA", "US-TX"), so a reader
    # can tell a state obligation from a federal one without parsing prose.
    jurisdiction: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    # The county or locality the determination covers. Determinations are
    # per-county; a project in the wrong county is citing the wrong document.
    locality: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    # The determination number exactly as issued. Free text - every authority
    # numbers these differently and none of the formats is ours to validate.
    identifier: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # published_schedule | local_wage_survey | federal_locality_determination.
    determination_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # ISO YYYY-MM-DD. ``decision_date`` is when the authority issued it,
    # ``effective_date`` when it starts to bind, ``expires_on`` when it stops.
    # All nullable: a determination with no stated expiry is the normal case.
    decision_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expires_on: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The statute the obligation rests on, e.g. "California Labor Code 1771" or
    # "Texas Government Code 2258.022(a)". Mirrors the state packs, which make
    # this field mandatory on every rule for the same reason: an unsourced wage
    # figure is worse than silence, because somebody will pay people on it.
    statute_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Where the contractor got the document, in its own words.
    source_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD", server_default="USD")
    # True once a certified week cites it. Immutable from then on.
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    classifications: Mapped[list["WageClassification"]] = relationship(
        back_populates="determination",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<WageDetermination {self.authority}:{self.identifier} {self.locality}>"


class WageClassification(Base):
    """One craft inside a determination, with basic and fringe held apart.

    There is deliberately no combined rate column. Anything needing the total
    package adds the two, which forces the caller to have both in hand and makes
    it impossible to persist a blended number that has lost the split.
    """

    __tablename__ = "oe_certpay_classification"
    __table_args__ = (UniqueConstraint("determination_id", "code", name="uq_oe_certpay_classification_det_code"),)

    determination_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_certpay_determination.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The craft code as the determination writes it, e.g. "ELEC0001-002".
    code: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # The craft in words, e.g. "Electrician" or "Laborer Group 1".
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # The basic hourly rate. Overtime is computed on THIS and nothing else.
    basic_hourly_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # The fringe benefit rate, per hour, held apart from the basic rate for the
    # whole life of the row. Paid to a plan or in cash; either way it is not
    # part of the base an overtime multiplier applies to.
    fringe_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Child -> parent scalar: the FK is already in the column, so an implicit
    # walk upwards is exactly the MissingGreenlet source the module rules warn
    # about. raise_on_sql still allows a free read when the parent is loaded.
    determination: Mapped[WageDetermination] = relationship(
        back_populates="classifications",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<WageClassification {self.code} {self.title} {self.basic_hourly_rate}+{self.fringe_rate}>"


class WorkerClassificationAssignment(Base):
    """Which classification a worker works under on a project.

    This is the join that did not exist before this module: field hours knew a
    resource, payroll knew a rate, and nothing said what craft the person was
    working as. Without it a paid rate cannot be compared to any determination,
    because nothing says which line of the determination applies.

    ``resource_id`` is a soft link with no foreign key, matching
    ``PayrollEntry.resource_id``: a certified payroll is kept for years and has
    to survive a resource being tidied out of the register. ``worker_name``
    carries the person either way, so a free-text worker with no resource record
    can still be classified.
    """

    __tablename__ = "oe_certpay_assignment"
    __table_args__ = (Index("ix_oe_certpay_assignment_project_resource", "project_id", "resource_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Soft link, no FK. See the class docstring.
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    worker_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # The identifying number the form asks for. Whatever the contractor uses;
    # never a national identifier this platform invents or validates.
    worker_identifier: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    classification_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_certpay_classification.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # ISO YYYY-MM-DD validity window. Both nullable: an assignment with no dates
    # is simply in force, which is what a small contractor will enter.
    valid_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # What this worker is actually paid, split the same way the determination
    # splits what they are owed. All three nullable, and that is the point: a
    # payroll entry carries one blended hourly rate, which cannot answer how
    # much of it was basic wage and how much was fringe, nor where the fringe
    # went. Stating it here makes the split real data. Left NULL, the service
    # derives a split from the payroll rate against the determination's basic
    # rate and says so, rather than inventing a fringe figure silently.
    paid_basic_rate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    paid_fringe_rate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # plan | cash | mixed - how the fringe for this worker is discharged.
    fringe_election: Mapped[str | None] = mapped_column(String(12), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<WorkerClassificationAssignment {self.worker_name} -> {self.classification_id}>"


class CertifiedPayrollWeek(Base):
    """One week of certified payroll for one project.

    A week in ``draft`` derives its rows live from the payroll entries and holds
    no lines of its own. Certifying it freezes those rows into
    :class:`CertifiedPayrollLine` and stamps the signature. A certified week is
    immutable; the correction is a new week for the same week-ending date with a
    higher payroll number, which is how the industry issues an amended payroll
    and mirrors the reversing-timesheet precedent in ``field_time``.
    """

    __tablename__ = "oe_certpay_week"
    __table_args__ = (Index("ix_oe_certpay_week_project_ending", "project_id", "week_ending"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Soft link to the payroll batch the rows were derived from, no FK: the
    # batch may be archived while the certified week survives.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # ISO YYYY-MM-DD of the last day of the payroll week. The form is keyed on
    # this, and ``period_label`` free text on the batch cannot carry it.
    week_ending: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # Sequential payroll number within the project, and whether this is the
    # final payroll for the contract. Both are printed on the form and neither
    # can be derived from the payroll data.
    payroll_number: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    contractor_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    contractor_address: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # The form distinguishes a contractor from a subcontractor, because a prime
    # is answerable for the payrolls of the subcontractors under it.
    is_subcontractor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    project_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    project_location: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    contract_number: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")

    # Which regimes cover this week: a list drawn from
    # ALL_DETERMINATION_AUTHORITIES, e.g. ``["federal", "state"]`` on a
    # federally funded California job. Both are owed; satisfying one does not
    # satisfy the other, so both are recorded rather than one being chosen.
    covered_authorities: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # Which determination actually governed the rates on this week, and why.
    # Where two regimes cover the same work the higher total package governs;
    # the reason is stored in words so the record says which one it used and on
    # what ground, rather than leaving a reader to re-derive it.
    governing_determination_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    governing_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    # plan | cash | mixed. The statement of compliance elects between paying
    # fringes into approved plans and paying them in cash, and a week-level
    # election is what the form prints; per-worker detail lives on the line.
    fringe_election: Mapped[str] = mapped_column(String(12), nullable=False, default="plan", server_default="plan")
    fringe_exception_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )
    # The signature. All nullable until somebody signs: an unsigned week is the
    # state every week starts in, and a server default here would have every
    # draft claiming to carry a statement of compliance it does not carry.
    signatory_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signatory_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The exact wording certified, frozen with the signature. Stored rather than
    # rendered on read, because the wording of a statement somebody signed must
    # not change when this application's copy of it does.
    statement_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    lines: Mapped[list["CertifiedPayrollLine"]] = relationship(
        back_populates="week",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<CertifiedPayrollWeek {self.week_ending} #{self.payroll_number} ({self.status})>"


class CertifiedPayrollLine(Base):
    """One worker's frozen week on a certified payroll.

    Written only at certification. Every reference to another table is
    denormalised alongside its id, because this row is the legal record: it has
    to read back the same in three years whatever happened since to the
    classification it named or the determination it cited.
    """

    __tablename__ = "oe_certpay_line"
    __table_args__ = (Index("ix_oe_certpay_line_week_ordinal", "week_id", "ordinal"),)

    week_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_certpay_week.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    worker_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    worker_identifier: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")

    # Soft ids plus the words. The ids let a reader navigate; the words are what
    # the record actually asserts and they never change.
    classification_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    classification_code: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    classification_title: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    determination_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    determination_identifier: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    determination_authority: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")

    # Hours spread across the days of the week, the shape the form prints:
    # ``{"2026-08-10": {"straight": "8", "overtime": "0"}, ...}``. ISO dates as
    # keys so the reader never has to guess which day a column meant.
    hours_by_day: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    straight_hours: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    overtime_hours: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")

    # What the determination required, frozen from the classification.
    required_basic_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    required_fringe_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # What the contractor asserts it paid, split the same way. Kept apart from
    # the required figures so underpayment is a comparison, not an assumption.
    paid_basic_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    paid_fringe_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # plan | cash | mixed, for this worker. The week carries the headline
    # election; a worker whose fringe went elsewhere is recorded here.
    fringe_election: Mapped[str] = mapped_column(String(12), nullable=False, default="plan", server_default="plan")

    # The overtime multiplier applied, and the base it was applied to. The base
    # is stored as a figure rather than recomputed, so the record can be checked
    # against the basic rate beside it without trusting this module's arithmetic.
    overtime_multiplier: Mapped[str] = mapped_column(String(20), nullable=False, default="1.5", server_default="1.5")
    overtime_base_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")

    gross_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    total_deductions: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    net_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # One entry per withholding: ``[{"label": ..., "type": ..., "amount": ...}]``.
    # The coarse type is ``oe_payroll``'s own tax/social/pension/other bucket,
    # mapped to the form's columns at the export boundary and never widened here.
    deductions_detail: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    week: Mapped[CertifiedPayrollWeek] = relationship(
        back_populates="lines",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<CertifiedPayrollLine {self.worker_name} {self.classification_title} {self.straight_hours}h>"
