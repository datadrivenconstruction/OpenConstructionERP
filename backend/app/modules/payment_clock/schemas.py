# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Payment clock Pydantic schemas - request/response models.

Money and percentages leave as plain-decimal **strings**. Pydantic v2 would
serialise a ``Decimal`` to a JSON number, which JavaScript truncates to a
double, and a payment application is the last place in the product where a
rounding artefact is acceptable. Currency is a required three-letter code on
anything carrying an amount: these regimes span six jurisdictions and an
implied currency is a bug waiting for a cross-border job.

Each ``Literal`` here is pinned equal to the matching tuple in
:mod:`app.modules.payment_clock.models` by the module's tests. The tuple is
what the seeded data and the date engine are written against and the Literal is
what the API rejects on, so a drift between them lets a value through that the
clock has no arithmetic for.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

DayBasisLiteral = Literal["calendar", "business"]
DateBasisLiteral = Literal["application_date", "period_end", "due_date"]
NoNoticeEffectLiteral = Literal[
    "applied_sum_becomes_notified_sum",
    "evidential_bar",
    "deemed_dispute",
    "none",
]
InterestBasisLiteral = Literal[
    "reference_rate_plus_margin",
    "prescribed_rate",
    "fixed_rate",
    "contract",
]
NoticeTypeLiteral = Literal["payment_notice", "pay_less_notice", "default_payment_notice"]
SourceTypeLiteral = Literal[
    "contracts_progress_claim",
    "subcontractors_payment_application",
    "manual",
]
ApplicationStatusLiteral = Literal["open", "paid", "disputed", "closed"]
EventTypeLiteral = Literal[
    "payment_notice_missed",
    "notice_out_of_time",
    "pay_less_notice_without_basis",
    "final_date_before_due_date",
    "payment_overdue",
]

# A deployment supplying its own public-holiday calendar for the business-day
# counts sends it per request. Sixty entries covers a year of public holidays in
# any of these jurisdictions with room to spare, including the statutory
# year-end exclusions in New South Wales and New Zealand.
MAX_HOLIDAYS = 60


def _money_string(value: Any) -> str | None:
    """Render a Decimal-ish value as a plain-decimal string, or ``None``.

    Same convention as the variations / property_dev / boq money fields: exact,
    locale-neutral, and never a JSON number. A non-finite value collapses to
    ``"0"`` rather than crashing the encoder.
    """
    if value is None:
        return None
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return "0"
    if not value.is_finite():
        return "0"
    return format(value, "f")


def _check_currency(value: str) -> str:
    """A three-letter ISO 4217 code, upper-cased. Empty is rejected upstream."""
    code = (value or "").strip().upper()
    if code and (len(code) != 3 or not code.isalpha()):
        raise ValueError("Currency must be a three-letter ISO 4217 code, for example GBP or SGD.")
    return code


# ── Regime ───────────────────────────────────────────────────────────────────


class RegimeResponse(BaseModel):
    """One statutory regime as the reader receives it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    jurisdiction: str
    country_code: str
    statute: str
    statute_reference: str
    due_date_basis: str
    due_date_days: int
    due_date_day_basis: str
    payment_notice_basis: str
    payment_notice_days: int | None
    payment_notice_day_basis: str
    final_date_basis: str
    final_date_days: int | None
    final_date_day_basis: str
    pay_less_days: int | None
    pay_less_day_basis: str
    no_notice_effect: str
    interest_basis: str
    interest_reference_rate: str
    interest_margin_percent: Decimal | None
    interest_fixed_percent: Decimal | None
    interest_statute: str
    notes: str
    # Filled by the router from the pure clock helper, not stored: the interest
    # clause as one readable sentence.
    interest_description: str = ""

    @field_serializer("interest_margin_percent", "interest_fixed_percent", when_used="json")
    @classmethod
    def _ser_percent(cls, value: Decimal | None) -> str | None:
        return _money_string(value)


class RegimeSeedRow(BaseModel):
    """One entry of :data:`app.modules.payment_clock.data.PAYMENT_REGIMES`.

    Exists so the load path validates a seeded row against the same Literal
    vocabulary the API rejects submitted data on. Before this, ``no_notice_
    effect`` and ``interest_basis`` were plain ``str`` columns on
    :class:`~app.modules.payment_clock.models.PaymentRegime`, and
    ``seed_payment_regimes`` built that model straight from a dict, so the
    parity test guarding :class:`NoNoticeEffectLiteral` and
    :class:`InterestBasisLiteral` against the model's tuples covered the API
    layer and never the path our own shipped data actually takes. A typo in
    :mod:`app.modules.payment_clock.data` would have seeded silently and only
    surfaced downstream, in whichever rule happened to read the bad value.

    ``model_config`` forbids extra fields so a misspelled key, not just a
    misspelled value, is refused here rather than reaching
    ``PaymentRegime(**entry)``.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    jurisdiction: str
    country_code: str
    statute: str
    statute_reference: str = ""
    due_date_basis: DateBasisLiteral
    due_date_days: int
    due_date_day_basis: DayBasisLiteral
    payment_notice_basis: DateBasisLiteral
    payment_notice_days: int | None = None
    payment_notice_day_basis: DayBasisLiteral
    final_date_basis: DateBasisLiteral
    final_date_days: int | None = None
    final_date_day_basis: DayBasisLiteral
    pay_less_days: int | None = None
    pay_less_day_basis: DayBasisLiteral
    no_notice_effect: NoNoticeEffectLiteral
    interest_basis: InterestBasisLiteral
    interest_reference_rate: str = ""
    interest_margin_percent: Decimal | None = None
    interest_fixed_percent: Decimal | None = None
    interest_statute: str = ""
    notes: str = ""


# ── Application ──────────────────────────────────────────────────────────────


class _ApplicationDates(BaseModel):
    """The four statutory dates, when a caller states them instead of computing.

    A contract is allowed to set its own compliant periods, and a clock opened
    from a paper file may already know the dates the parties worked to. Sending
    any of these marks the row overridden, and the recompute then leaves it
    alone unless it is told explicitly to take the dates back.
    """

    due_date: date | None = None
    payment_notice_deadline: date | None = None
    pay_less_deadline: date | None = None
    final_date: date | None = None


class ApplicationCreate(_ApplicationDates):
    """Open a payment clock over an application."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    # By code rather than by id: the code is stable across deployments, so a
    # seeded demo, an import and an integration all name the same regime.
    regime_code: str = Field(min_length=1, max_length=40)
    source_type: SourceTypeLiteral = "manual"
    # The progress claim or subcontractor payment application this clock is
    # about. Not a foreign key - it points at either of two tables in two other
    # modules - so nothing here can check it resolves.
    source_id: UUID | None = None
    reference: str = Field(default="", max_length=64)
    application_date: date
    period_start: date | None = None
    period_end: date | None = None
    applied_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    status: ApplicationStatusLiteral = "open"
    paid_at: date | None = None
    paid_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    notes: str = Field(default="", max_length=4000)
    holidays: list[date] = Field(default_factory=list, max_length=MAX_HOLIDAYS)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return _check_currency(value)

    @model_validator(mode="after")
    def _period_in_order(self) -> ApplicationCreate:
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("The period end cannot fall before the period start.")
        return self

    @field_serializer("applied_amount", "paid_amount", when_used="json")
    @classmethod
    def _ser_money(cls, value: Decimal | None) -> str | None:
        return _money_string(value)


class ApplicationUpdate(BaseModel):
    """Change an open clock. Only the fields sent are touched.

    A partial update rather than a full replace: the four computed dates live on
    the same row as the facts they were computed from, and a full PUT from a
    screen that only knows about the payment would blank them.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str | None = Field(default=None, max_length=64)
    application_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    applied_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: ApplicationStatusLiteral | None = None
    paid_at: date | None = None
    paid_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=4000)
    due_date: date | None = None
    payment_notice_deadline: date | None = None
    pay_less_deadline: date | None = None
    final_date: date | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str | None) -> str | None:
        return _check_currency(value) if value is not None else None


class RecomputeRequest(BaseModel):
    """Recompute the statutory dates from the regime.

    ``force`` is needed to overwrite dates somebody set by hand; without it a
    recompute over an overridden row is refused rather than silently replacing
    the dates the parties were working to.
    """

    force: bool = False
    holidays: list[date] = Field(default_factory=list, max_length=MAX_HOLIDAYS)


class ApplicationResponse(BaseModel):
    """One payment application with its stored statutory dates."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    regime_id: UUID
    source_type: str
    source_id: UUID | None
    reference: str
    application_date: date
    period_start: date | None
    period_end: date | None
    applied_amount: Decimal
    currency: str
    due_date: date | None
    payment_notice_deadline: date | None
    pay_less_deadline: date | None
    final_date: date | None
    dates_overridden: bool
    status: str
    paid_at: date | None
    paid_amount: Decimal | None
    notes: str
    created_at: datetime
    updated_at: datetime
    # Filled by the router from the regime row, not stored on the application.
    regime_code: str = ""
    jurisdiction: str = ""

    @field_serializer("applied_amount", "paid_amount", when_used="json")
    @classmethod
    def _ser_money(cls, value: Decimal | None) -> str | None:
        return _money_string(value)


# ── Notice ───────────────────────────────────────────────────────────────────


class NoticeCreate(BaseModel):
    """Record a notice that was served."""

    model_config = ConfigDict(str_strip_whitespace=True)

    notice_type: NoticeTypeLiteral
    issued_at: date
    notified_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    # Left empty, the application's currency is used. Stating a different one is
    # allowed and is not corrected here: a notice served in another currency is
    # a fact about the notice, and a rule flags the mismatch rather than hiding
    # it behind a silent rewrite.
    currency: str = Field(default="", max_length=3)
    basis_of_calculation: str = Field(default="", max_length=8000)
    served_by: str = Field(default="", max_length=200)
    served_to: str = Field(default="", max_length=200)
    reference: str = Field(default="", max_length=64)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return _check_currency(value)

    @field_serializer("notified_amount", when_used="json")
    @classmethod
    def _ser_money(cls, value: Decimal | None) -> str | None:
        return _money_string(value)


class NoticeResponse(BaseModel):
    """One served notice as the reader receives it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    notice_type: str
    issued_at: date
    notified_amount: Decimal | None
    currency: str
    basis_of_calculation: str
    served_by: str
    served_to: str
    reference: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("notified_amount", when_used="json")
    @classmethod
    def _ser_money(cls, value: Decimal | None) -> str | None:
        return _money_string(value)


# ── Findings, events and the computed clock ──────────────────────────────────


class ClockFinding(BaseModel):
    """One validation finding shown beside the application.

    ``key`` is what the reader translates; ``message`` is the English the rule
    wrote and is shown only where a locale has no string for the key yet. The
    same split the cases findings use.
    """

    key: str
    rule_id: str
    severity: str
    message: str
    suggestion: str = ""
    details: dict = Field(default_factory=dict)


class EventResponse(BaseModel):
    """One recorded breach."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    event_type: str
    severity: str
    rule_id: str
    detected_at: datetime
    deadline_date: date | None
    days_late: int | None
    amount: Decimal | None
    currency: str
    consequence: str
    detail: dict
    created_at: datetime

    @field_serializer("amount", when_used="json")
    @classmethod
    def _ser_money(cls, value: Decimal | None) -> str | None:
        return _money_string(value)


class NotifiedSum(BaseModel):
    """The sum that is actually payable, and why it is that sum.

    This is the answer the module exists to give. Where the payer served a
    valid notice, it is the sum that notice stated. Where the payer let the
    window close, it is the sum the contractor applied for, and no defence to
    it survives - which is the sentence that decides adjudications.
    """

    amount: Decimal | None = None
    currency: str = ""
    source: str = "undetermined"
    explanation: str = ""
    # The same answer in a form a screen can translate. ``source`` cannot serve:
    # three different answers share ``undetermined``. Empty on a stored reading
    # written before the codes existed, which is why the page keeps the prose as
    # its fallback rather than showing nothing.
    reason: str = ""
    params: dict[str, str] = Field(default_factory=dict)

    @field_serializer("amount", when_used="json")
    @classmethod
    def _ser_money(cls, value: Decimal | None) -> str | None:
        return _money_string(value)


class ApplicationClock(BaseModel):
    """Everything computed about one application, in one object."""

    application: ApplicationResponse
    notices: list[NoticeResponse] = Field(default_factory=list)
    events: list[EventResponse] = Field(default_factory=list)
    findings: list[ClockFinding] = Field(default_factory=list)
    notified_sum: NotifiedSum = Field(default_factory=NotifiedSum)
    derivation: list[str] = Field(default_factory=list)
    interest_description: str = ""


__all__ = [
    "MAX_HOLIDAYS",
    "ApplicationClock",
    "ApplicationCreate",
    "ApplicationResponse",
    "ApplicationUpdate",
    "ClockFinding",
    "EventResponse",
    "NoticeCreate",
    "NoticeResponse",
    "NotifiedSum",
    "RecomputeRequest",
    "RegimeResponse",
    "RegimeSeedRow",
]
