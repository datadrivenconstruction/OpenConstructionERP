# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Payment clock ORM models.

Tables:
    oe_payment_clock_regime      - one statutory payment regime
    oe_payment_clock_application - a payment application under a regime
    oe_payment_clock_notice      - a notice served in the sequence
    oe_payment_clock_event       - a computed breach and its consequence

The class is called :class:`StatutoryPaymentApplication` rather than
``PaymentApplication`` because two other modules already declare a model by
that name (``subcontractors`` and ``cvr``), and the thing stored here is not a
third payment application. It is the statutory clock *over* an application that
lives somewhere else: the same subcontractor payment application can be one row
there and one row here, and the two say different things.

No ``relationship()`` is declared anywhere in this module. A notice and an
event point at their application by id, and an application points at its
regime by id, so every read is an explicit query and there is no lazy-loading
strategy to get wrong.

Nothing is ever queried *inside* a JSON column. On PostgreSQL a ``.contains()``
on a plain JSON column compiles to a string LIKE rather than to JSONB
containment, so a filter written that way would silently mean something else.
``PaymentClockEvent.detail`` is written and read whole.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
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

# ── Vocabularies ─────────────────────────────────────────────────────────────
#
# Every one of these is mirrored by a ``Literal`` in
# :mod:`app.modules.payment_clock.schemas` and pinned equal to it by
# ``tests/unit/test_payment_clock_module.py``. The tuple is what the seeded data
# and the date engine are written against; the Literal is what the API rejects
# on. A drift between them lets a value through the door that the clock has no
# arithmetic for.

# How a deadline counts days. Australian and Singaporean statutes say "business
# days", the New Zealand Act says "working days"; both mean the same thing here
# and both map to ``business``. What counts as a non-working day beyond Saturday
# and Sunday is a per-jurisdiction calendar the deployment supplies - see
# :mod:`app.modules.payment_clock.clock`.
DAY_BASES: tuple[str, ...] = ("calendar", "business")

# What a computed date counts *from*.
DATE_BASES: tuple[str, ...] = ("application_date", "period_end", "due_date")

# What the statute makes of a payment notice that was never served. These are
# three genuinely different consequences and the difference is the reason this
# is a column rather than a constant:
#
#   applied_sum_becomes_notified_sum - the sum applied for becomes the sum
#       payable, and no defence to it survives. This is the rule the module
#       exists for (United Kingdom, Ireland, New South Wales, Queensland,
#       New Zealand).
#   evidential_bar - the payer stays free to dispute the amount but may not
#       raise at adjudication any reason it did not put in the response
#       (Singapore).
#   deemed_dispute - failing to respond disputes the whole claim rather than
#       conceding it, so the claimant's next step is adjudication, not a debt
#       claim (Malaysia).
#   none - the regime has no notice sequence at all and only supplies a
#       payment period and an interest basis (the EU Late Payment Directive
#       and the German VOB/B and BGB regimes).
NO_NOTICE_EFFECTS: tuple[str, ...] = (
    "applied_sum_becomes_notified_sum",
    "evidential_bar",
    "deemed_dispute",
    "none",
)

# How statutory interest on a late payment is set.
INTEREST_BASES: tuple[str, ...] = (
    "reference_rate_plus_margin",
    "prescribed_rate",
    "fixed_rate",
    "contract",
)

# The three notices in the sequence. A default payment notice is the payee's
# own notice, served when the payer let the payment-notice window close.
NOTICE_TYPES: tuple[str, ...] = (
    "payment_notice",
    "pay_less_notice",
    "default_payment_notice",
)

# Which table the application being clocked actually lives in. A plain
# discriminator plus a plain id, never a foreign key, because it can point at
# either of two tables in two other modules - or at nothing, when the clock was
# opened by hand before the claim was recorded anywhere else.
SOURCE_TYPES: tuple[str, ...] = (
    "contracts_progress_claim",
    "subcontractors_payment_application",
    "manual",
)

APPLICATION_STATUSES: tuple[str, ...] = ("open", "paid", "disputed", "closed")

# A computed breach. Each one is raised by exactly one validation rule and
# carries that rule's id, so the register and the findings never disagree about
# what happened.
EVENT_TYPES: tuple[str, ...] = (
    "payment_notice_missed",
    "notice_out_of_time",
    "pay_less_notice_without_basis",
    "final_date_before_due_date",
    "payment_overdue",
)

EVENT_SEVERITIES: tuple[str, ...] = ("error", "warning")


class PaymentRegime(Base):
    """One statutory payment regime: the dates a jurisdiction imposes.

    Reference data, not user data. The rows are seeded from
    :mod:`app.modules.payment_clock.data`, which is where the statutory values
    are written down and sourced; the table exists so an application can point
    at the regime it was computed under and keep pointing at it after the
    catalogue is updated.

    Deadlines are nullable because not every regime has every step. Malaysia
    leaves the final date for payment to the contract, and the EU Late Payment
    Directive is an interest basis with no notice sequence at all. A null means
    "this statute is silent", which is a different statement from zero days.
    """

    __tablename__ = "oe_payment_clock_regime"
    __table_args__ = (
        UniqueConstraint("code", name="uq_payment_clock_regime_code"),
        Index("ix_payment_clock_regime_country", "country_code"),
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(120), nullable=False)
    # ISO 3166-1 alpha-2, or "EU" for the union-wide directive. A sub-national
    # regime carries its country: New South Wales and Queensland are both "AU".
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="", server_default="")
    statute: Mapped[str] = mapped_column(String(200), nullable=False)
    statute_reference: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")

    due_date_basis: Mapped[str] = mapped_column(String(24), nullable=False, default="application_date")
    due_date_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    due_date_day_basis: Mapped[str] = mapped_column(String(16), nullable=False, default="calendar")

    # Not later than N days after the basis date. Null where the regime has no
    # payment notice.
    payment_notice_basis: Mapped[str] = mapped_column(String(24), nullable=False, default="due_date")
    payment_notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_notice_day_basis: Mapped[str] = mapped_column(String(16), nullable=False, default="calendar")

    final_date_basis: Mapped[str] = mapped_column(String(24), nullable=False, default="application_date")
    final_date_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_date_day_basis: Mapped[str] = mapped_column(String(16), nullable=False, default="calendar")

    # Not later than N days *before* the final date, counted backwards. Null in
    # the regimes where the payment notice is the only response the statute
    # provides for.
    pay_less_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pay_less_day_basis: Mapped[str] = mapped_column(String(16), nullable=False, default="calendar")

    no_notice_effect: Mapped[str] = mapped_column(String(48), nullable=False, default="none")

    interest_basis: Mapped[str] = mapped_column(String(32), nullable=False, default="contract")
    interest_reference_rate: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    interest_margin_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    interest_fixed_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    interest_statute: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")

    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<PaymentRegime {self.code} {self.jurisdiction}>"


class StatutoryPaymentApplication(Base):
    """A payment application, with the statutory dates the regime imposes on it.

    ``source_type`` + ``source_id`` point at the row this clock is about. It is
    deliberately not a foreign key: the target is a progress claim in the
    contracts module or a payment application in the subcontractors module, two
    different tables, and no column can reference both. ``manual`` means the
    clock was opened here first and there is no target yet.

    The four computed dates are stored rather than derived on read. A statutory
    date is evidence: it has to survive the regime catalogue being corrected
    afterwards, and an adjudicator asking what the deadline was on the day
    wants the date the parties were working to, not a recomputation under
    today's data. :func:`app.modules.payment_clock.service.recompute_schedule`
    is the only thing that rewrites them, and it says so when it does.
    """

    __tablename__ = "oe_payment_clock_application"
    __table_args__ = (
        # One clock per source row. ``manual`` rows carry a null ``source_id``
        # and PostgreSQL treats nulls as distinct, so any number of them coexist
        # while a given progress claim can only ever be clocked once.
        UniqueConstraint("source_type", "source_id", name="uq_payment_clock_application_source"),
        # ``app.core.pg_optimizations`` adds both of these on the ``create_all``
        # path and does not run on the alembic path. Declaring them here, with
        # the names that generator would pick, is what keeps an upgraded
        # deployment and a fresh install on the same schema.
        Index("ix_oe_payment_clock_application_project_id_created_at", "project_id", "created_at"),
        Index("ix_oe_payment_clock_application_project_id_status", "project_id", "status"),
        Index("ix_payment_clock_application_final_date", "final_date"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    regime_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        # RESTRICT, not CASCADE: a regime is reference data and deleting one out
        # from under a live application would take the evidence with it.
        #
        # Named explicitly because the metadata convention would produce
        # ``fk_oe_payment_clock_application_regime_id_oe_payment_clock_regime``,
        # 65 characters against PostgreSQL's 63-character identifier limit. A
        # name over the limit gets shortened with a hash on the ``create_all``
        # path and would have to be hand-shortened the same way in the
        # migration, so the two install routes would drift on a constraint name
        # nobody would think to compare. Short enough to survive is the fix.
        ForeignKey(
            "oe_payment_clock_regime.id",
            ondelete="RESTRICT",
            name="fk_payment_clock_application_regime",
        ),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, default="manual")
    source_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    reference: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    # The date the application (payment claim) was served. Every other date in
    # the sequence is counted from this or from what this produces.
    application_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    applied_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    # Explicit per row. These modules are multinational by definition and an
    # amount with an implied currency is a bug waiting for a cross-border job.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_notice_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    pay_less_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    final_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Set when the dates came from somewhere other than the regime arithmetic -
    # a contract that sets its own compliant periods, or a hand correction. The
    # recompute refuses to overwrite an overridden row without being told to.
    dates_overridden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", server_default="open")
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<StatutoryPaymentApplication {self.reference or self.id} {self.applied_amount} {self.currency}>"


class PaymentNotice(Base):
    """One notice served in the statutory sequence.

    ``served_by`` and ``served_to`` are party names as written, not user ids: a
    notice is commonly served by or on a company that has no account here, and
    the name that matters is the one on the notice.

    ``basis_of_calculation`` is what a pay-less notice lives or dies by. A
    pay-less notice that does not say how the withheld sum was arrived at is
    not a valid pay-less notice, which is why the column is not nullable and
    why a rule checks it is not empty either.
    """

    __tablename__ = "oe_payment_clock_notice"
    __table_args__ = (Index("ix_payment_clock_notice_application_type", "application_id", "notice_type"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        # Named explicitly for the same reason as the regime key above: the
        # convention name runs to 70 characters and PostgreSQL stops at 63.
        ForeignKey(
            "oe_payment_clock_application.id",
            ondelete="CASCADE",
            name="fk_payment_clock_notice_application",
        ),
        nullable=False,
        index=True,
    )
    notice_type: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[date] = mapped_column(Date, nullable=False)
    notified_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    basis_of_calculation: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    served_by: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    served_to: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    reference: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<PaymentNotice {self.notice_type} {self.issued_at}>"


class PaymentClockEvent(Base):
    """A computed breach: what was missed, by how long, and what follows.

    Written by :func:`app.modules.payment_clock.service.record_clock_events`
    from the validation findings, so the register and the findings are the same
    statements twice rather than two implementations of the same law.

    ``consequence`` is prose on purpose. The row exists to be read by somebody
    deciding what to do next, and "the notified sum is the sum applied for" is
    the sentence that decides it.
    """

    __tablename__ = "oe_payment_clock_event"
    __table_args__ = (Index("ix_payment_clock_event_application_type", "application_id", "event_type"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        # Named explicitly; see the note on the notice table's key.
        ForeignKey(
            "oe_payment_clock_application.id",
            ondelete="CASCADE",
            name="fk_payment_clock_event_application",
        ),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="error")
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The deadline that was missed, and the gap in calendar days. Calendar even
    # where the deadline itself is counted in business days: "eleven days late"
    # is how long the payer actually had, and a business-day count would flatter
    # a breach that ran over a holiday.
    deadline_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    days_late: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    consequence: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    detail: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<PaymentClockEvent {self.event_type} app={self.application_id}>"
