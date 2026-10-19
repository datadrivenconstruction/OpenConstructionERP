# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The payment clock arithmetic. Pure functions, no database, no ORM.

Everything here takes a plain mapping in the shape of one entry of
:data:`app.modules.payment_clock.data.PAYMENT_REGIMES` and returns plain
values, so the statutory arithmetic can be read and tested on its own. The
service layer converts an ORM row into that shape with
:func:`app.modules.payment_clock.service.regime_spec` and never asks this
module to touch a session.

The sequence, in the order a job actually runs it::

    application  ->  due date  ->  payment notice deadline
                 ->  pay-less deadline  ->  final date for payment
                 ->  statutory interest

Two things about counting days are worth stating plainly because getting them
wrong moves every date in the sequence.

**Business days are Monday to Friday minus a calendar the deployment
supplies.** Australian and Singaporean statutes say "business days", the New
Zealand Act says "working days", and both mean a day that is not a weekend and
not a public holiday. Public holidays are not shipped here: they differ by
jurisdiction and change every year, and a wrong holiday list is worse than an
honest weekends-only count because it produces a date nobody can reproduce.
Callers with a holiday calendar pass it as ``holidays``. Two statutory
year-end exclusions are in the same position and are noted on their regimes:
New South Wales excludes 27 to 31 December, and New Zealand excludes 24
December to 5 January.

**Day one is the day after the start date.** "Not later than five days after
the due date" means the five days begin the day after, which is how every one
of these statutes counts and how a court reads them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.currency_registry import sentence_amount
from app.core.day_basis import add_days, is_business_day, working_week_for


@dataclass(frozen=True)
class ClockSchedule:
    """The four statutory dates for one application, and how they were reached.

    Any of the four may be ``None``. That is not a failure: a regime is allowed
    to be silent, and a null says the statute does not set that date rather
    than that the arithmetic gave up. Malaysia leaves the final date for
    payment to the contract; the EU Late Payment Directive has no notice
    sequence at all.
    """

    due_date: date | None = None
    payment_notice_deadline: date | None = None
    pay_less_deadline: date | None = None
    final_date: date | None = None
    # One line per computed date, in the order they were computed. This is what
    # gets shown next to the dates in the UI and quoted in a dispute, so it
    # names the statute rather than describing the code.
    derivation: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """ISO strings plus the derivation, ready for a response or a rule."""
        return {
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "payment_notice_deadline": (
                self.payment_notice_deadline.isoformat() if self.payment_notice_deadline else None
            ),
            "pay_less_deadline": self.pay_less_deadline.isoformat() if self.pay_less_deadline else None,
            "final_date": self.final_date.isoformat() if self.final_date else None,
            "derivation": list(self.derivation),
        }


# ── Day arithmetic ───────────────────────────────────────────────────────────


# ``is_business_day`` and ``add_days`` now live in :mod:`app.core.day_basis` and
# are imported above, so this module's callers and tests keep reaching them here
# unchanged. They moved because the contractual notice and time-bar engine in
# ``oe_change_intelligence`` counts the same periods, and this module is regional
# and switchable off: a controls module must not lose its day arithmetic when a
# deployment outside a security-of-payment jurisdiction removes this one. The
# reasoning about business days and about shipping no holiday lists moved with
# them and is restated there.


def days_between(earlier: date, later: date) -> int:
    """Calendar days from ``earlier`` to ``later``; negative when reversed.

    Calendar even where the deadline it measures was counted in business days.
    "Eleven days late" is how long the other side actually waited, and a
    business-day count would flatter a breach that ran over a holiday.
    """
    return (later - earlier).days


# ── Coercion helpers ─────────────────────────────────────────────────────────


def parse_date(value: Any) -> date | None:
    """A ``date`` from a date, a datetime or an ISO string; ``None`` otherwise.

    Rules receive their data as a plain dict that may have come from an ORM row
    or from JSON, so both shapes have to land in the same place.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def parse_money(value: Any) -> Decimal | None:
    """A ``Decimal`` from anything money-shaped; ``None`` when it is not."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def format_money(amount: Decimal | None, currency: str = "") -> str:
    """An amount and its currency as one string, for a message a person reads.

    The spelling is the platform's, :func:`app.core.currency_registry.sentence_amount`,
    rather than one of this module's own. It used to be one of this module's own:
    it named the currency but never grouped the digits and never asked the
    currency how many decimals it keeps, so a sum this module wrote as
    ``1234.50 GBP`` appeared two panels away, from the same underlying figure, as
    ``1,234.50 GBP``.

    The absent case stays a sentence rather than a number. ``None`` here means
    the record states no amount, which is a different fact from zero, and this
    module reaches that case often enough that printing ``None`` into a statutory
    notice would be a visible defect.
    """
    if amount is None:
        return "an unstated amount"
    return sentence_amount(amount, currency)


# ── The schedule ─────────────────────────────────────────────────────────────


def _basis_date(basis: str, application_date: date, period_end: date | None, due_date: date | None) -> date | None:
    if basis == "application_date":
        return application_date
    if basis == "period_end":
        # The UK Scheme counts from the end of the relevant period, "or the
        # making of a claim by the payee" where there is no period. Falling back
        # to the application date is that second limb, not a guess.
        return period_end or application_date
    if basis == "due_date":
        return due_date
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_schedule(
    regime: Mapping[str, Any],
    *,
    application_date: date,
    period_end: date | None = None,
    holidays: Iterable[date] = (),
) -> ClockSchedule:
    """Every statutory date for one application under one regime.

    Args:
        regime: One regime in the shape of a
            :data:`app.modules.payment_clock.data.PAYMENT_REGIMES` entry.
        application_date: The date the payment application (payment claim) was
            served. Every other date descends from this one.
        period_end: The end of the period claimed for, where the regime counts
            its due date from that rather than from the application.
        holidays: Non-working days beyond weekends, for the business-day counts.

    Returns:
        A :class:`ClockSchedule`. A date the statute does not set is ``None``.
    """
    holiday_set = set(holidays)
    # Business days are counted on the regime country's own week: Sunday to
    # Thursday in Saudi Arabia, Monday to Friday where the table names none.
    week = working_week_for(regime.get("country_code"))
    statute = str(regime.get("statute") or "the applicable statute")
    derivation: list[str] = []

    due_basis = str(regime.get("due_date_basis") or "application_date")
    due_days = _int_or_none(regime.get("due_date_days")) or 0
    due_day_basis = str(regime.get("due_date_day_basis") or "calendar")
    due_from = _basis_date(due_basis, application_date, period_end, None)
    due_date = add_days(due_from, due_days, due_day_basis, holiday_set, week) if due_from else None
    if due_date is not None and due_from is not None:
        derivation.append(
            f"Due date {due_date.isoformat()}: {_after_phrase(due_days, due_day_basis, due_basis, due_from)} "
            f"under {statute}."
        )

    notice_days = _int_or_none(regime.get("payment_notice_days"))
    notice_deadline: date | None = None
    if notice_days is not None:
        notice_basis = str(regime.get("payment_notice_basis") or "due_date")
        notice_day_basis = str(regime.get("payment_notice_day_basis") or "calendar")
        notice_from = _basis_date(notice_basis, application_date, period_end, due_date)
        if notice_from is not None:
            notice_deadline = add_days(notice_from, notice_days, notice_day_basis, holiday_set, week)
            derivation.append(
                f"Payment notice not later than {notice_deadline.isoformat()}: "
                f"{_after_phrase(notice_days, notice_day_basis, notice_basis, notice_from)}."
            )

    final_days = _int_or_none(regime.get("final_date_days"))
    final_date: date | None = None
    if final_days is not None:
        final_basis = str(regime.get("final_date_basis") or "application_date")
        final_day_basis = str(regime.get("final_date_day_basis") or "calendar")
        final_from = _basis_date(final_basis, application_date, period_end, due_date)
        if final_from is not None:
            final_date = add_days(final_from, final_days, final_day_basis, holiday_set, week)
            derivation.append(
                f"Final date for payment {final_date.isoformat()}: "
                f"{_after_phrase(final_days, final_day_basis, final_basis, final_from)}."
            )

    pay_less_days = _int_or_none(regime.get("pay_less_days"))
    pay_less_deadline: date | None = None
    if pay_less_days is not None and final_date is not None:
        pay_less_day_basis = str(regime.get("pay_less_day_basis") or "calendar")
        # Counted backwards from the final date, which is what "not later than
        # N days before the final date for payment" says.
        pay_less_deadline = add_days(final_date, -pay_less_days, pay_less_day_basis, holiday_set, week)
        derivation.append(
            f"Pay-less notice not later than {pay_less_deadline.isoformat()}: "
            f"{_days_phrase(pay_less_days, pay_less_day_basis)} before the final date "
            f"{final_date.isoformat()}."
        )

    return ClockSchedule(
        due_date=due_date,
        payment_notice_deadline=notice_deadline,
        pay_less_deadline=pay_less_deadline,
        final_date=final_date,
        derivation=derivation,
    )


def _days_phrase(days: int, basis: str) -> str:
    unit = "business day" if basis == "business" else "day"
    return f"{days} {unit}" if days == 1 else f"{days} {unit}s"


def _basis_phrase(basis: str) -> str:
    return {
        "application_date": "the application date",
        "period_end": "the end of the period claimed",
        "due_date": "the due date",
    }.get(basis, basis)


def _after_phrase(days: int, day_basis: str, basis: str, from_date: date) -> str:
    """Render an offset: 5 days after the due date 2026-03-06, or on that date.

    A statute that makes the sum due on the day the claim is served is a real
    case - most of the shipped regimes do exactly that - and "0 days after"
    reads like arithmetic that failed rather than a rule that says "on".
    """
    where = f"{_basis_phrase(basis)} {from_date.isoformat()}"
    if days == 0:
        return f"on {where}"
    return f"{_days_phrase(days, day_basis)} after {where}"


# ── Notices ──────────────────────────────────────────────────────────────────


def deadline_for_notice(notice_type: str, schedule: ClockSchedule) -> tuple[date | None, str]:
    """The deadline a notice of this type had to be served by, and its name.

    A default payment notice is the payee's own notice and the statutes do not
    put a deadline on it - it becomes available *because* the payer missed one -
    so it returns ``None`` and is never late.
    """
    if notice_type == "payment_notice":
        return schedule.payment_notice_deadline, "the payment notice deadline"
    if notice_type == "pay_less_notice":
        return schedule.pay_less_deadline, "the pay-less notice deadline"
    return None, "no statutory deadline"


# ── Interest ─────────────────────────────────────────────────────────────────


def interest_description(regime: Mapping[str, Any]) -> str:
    """How statutory interest runs under this regime, as one readable clause.

    The rate itself is deliberately not computed. A reference rate is a live
    figure published by a central bank, and inventing one here would put a
    number in front of a quantity surveyor that no source backs.
    """
    basis = str(regime.get("interest_basis") or "contract")
    reference = str(regime.get("interest_reference_rate") or "").strip()
    margin = parse_money(regime.get("interest_margin_percent"))
    fixed = parse_money(regime.get("interest_fixed_percent"))
    statute = str(regime.get("interest_statute") or "").strip()

    if basis == "reference_rate_plus_margin" and reference and margin is not None:
        clause = f"{reference} plus {_percent(margin)}"
    elif basis == "prescribed_rate":
        prescribed = f"the rate prescribed by {reference}" if reference else "the prescribed rate"
        clause = f"{prescribed}, or {_percent(fixed)} a year, whichever is greater" if fixed is not None else prescribed
    elif basis == "fixed_rate" and fixed is not None:
        clause = f"{_percent(fixed)} a year"
    else:
        clause = "the rate the contract specifies"

    return f"{clause} ({statute})" if statute else clause


def _percent(value: Decimal | None) -> str:
    if value is None:
        return "an unstated rate"
    normalised = value.normalize()
    # ``normalize`` turns 8.000 into 8E+0; quantize it back to a plain integer
    # so the message reads "8 percent" and not "8E+0 percent".
    if normalised == normalised.to_integral_value():
        normalised = normalised.to_integral_value()
    return f"{format(normalised, 'f')} percent"


__all__ = [
    "ClockSchedule",
    "add_days",
    "compute_schedule",
    "days_between",
    "deadline_for_notice",
    "format_money",
    "interest_description",
    "is_business_day",
    "parse_date",
    "parse_money",
]
