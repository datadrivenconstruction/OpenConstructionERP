# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment clock service - regimes, applications, notices and the register.

Stateless helpers over the four models. The statutory arithmetic itself is not
here: it lives in :mod:`app.modules.payment_clock.clock` as pure functions over
plain mappings, and this layer's job is to turn ORM rows into those mappings,
store what comes back, and keep the breach register in step with the findings.

Two decisions worth knowing before reading:

**The four dates are stored, not derived on read.** A statutory date is
evidence. It has to survive the regime catalogue being corrected next month,
and somebody asking what the deadline was wants the date the parties were
working to. :func:`recompute_schedule` is the only writer, and it refuses to
overwrite dates a person set by hand unless it is told to.

**The register mirrors the findings rather than reimplementing them.**
:func:`record_clock_events` takes the validation findings and files one row per
finding, keyed by rule and by what the finding was about, so the register and
the screen can never disagree about what the statute says happened.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payment_clock.clock import (
    ClockSchedule,
    compute_schedule,
    format_money,
    interest_description,
    parse_date,
    parse_money,
)
from app.modules.payment_clock.data import seed_payment_regimes
from app.modules.payment_clock.models import (
    PaymentClockEvent,
    PaymentNotice,
    PaymentRegime,
    StatutoryPaymentApplication,
)
from app.modules.payment_clock.repository import (
    TERMINAL_STATUSES,
    get_application,
    get_notice,
    get_regime,
    get_regime_by_code,
    list_applications,
    list_events,
    list_notices,
    list_regimes,
)
from app.modules.payment_clock.repository import add_application as _repo_add_application
from app.modules.payment_clock.repository import add_event as _repo_add_event
from app.modules.payment_clock.repository import add_notice as _repo_add_notice
from app.modules.payment_clock.repository import count_regimes as _repo_count_regimes
from app.modules.payment_clock.repository import delete_stale_events as _repo_delete_stale_events
from app.modules.payment_clock.repository import flush_application as _repo_flush_application
from app.modules.payment_clock.repository import flush_events as _repo_flush_events
from app.modules.payment_clock.repository import list_events_for_application as _repo_list_events_for_application
from app.modules.payment_clock.repository import remove_application as _repo_remove_application
from app.modules.payment_clock.repository import remove_notice as _repo_remove_notice
from app.modules.payment_clock.schemas import ApplicationCreate, ApplicationUpdate, NoticeCreate
from app.modules.payment_clock.validators import RULE_EVENT_TYPES

logger = logging.getLogger(__name__)

# Columns of :class:`PaymentRegime` that are the row's identity or its
# bookkeeping rather than part of the statutory specification.
_NON_SPEC_COLUMNS = frozenset({"id", "created_at", "updated_at"})


# ── Regimes ──────────────────────────────────────────────────────────────────


def regime_spec(regime: PaymentRegime) -> dict[str, Any]:
    """One regime row as the plain mapping the clock helpers take.

    Built from the table's own columns rather than a hand-written field list,
    so a column added to the model reaches the arithmetic without a second edit
    somewhere else. Decimals become strings on the way out: the mapping ends up
    inside validation findings and JSON columns, and ``parse_money`` reads a
    string as happily as a Decimal.
    """
    spec: dict[str, Any] = {}
    for column in regime.__table__.columns:
        if column.name in _NON_SPEC_COLUMNS:
            continue
        value = getattr(regime, column.name, None)
        spec[column.name] = format(value, "f") if isinstance(value, Decimal) else value
    return spec


async def ensure_regimes(session: AsyncSession, *, refresh: bool = False) -> dict[str, int]:
    """Seed the statutory catalogue if it is empty (or refresh it on request).

    Reference data, so it is loaded on demand rather than by a migration: the
    statutory values belong in :mod:`app.modules.payment_clock.data` where they
    can be read and corrected, and a migration that carried them would freeze a
    2026 reading of six statutes into the schema history.
    """
    if not refresh:
        count = await _repo_count_regimes(session)
        if count:
            return {"created": 0, "updated": 0, "unchanged": count}
    return await seed_payment_regimes(session, refresh=refresh)


# ── The schedule ─────────────────────────────────────────────────────────────


def build_schedule(
    regime: PaymentRegime,
    *,
    application_date: date,
    period_end: date | None = None,
    holidays: Iterable[date] = (),
) -> ClockSchedule:
    """The statutory dates for one application under one regime."""
    return compute_schedule(
        regime_spec(regime),
        application_date=application_date,
        period_end=period_end,
        holidays=holidays,
    )


def apply_schedule(application: StatutoryPaymentApplication, schedule: ClockSchedule) -> None:
    """Copy a computed schedule onto the row. Does not flush."""
    application.due_date = schedule.due_date
    application.payment_notice_deadline = schedule.payment_notice_deadline
    application.pay_less_deadline = schedule.pay_less_deadline
    application.final_date = schedule.final_date


async def recompute_schedule(
    session: AsyncSession,
    *,
    application: StatutoryPaymentApplication,
    regime: PaymentRegime,
    force: bool = False,
    holidays: Iterable[date] = (),
) -> tuple[ClockSchedule, bool]:
    """Recompute and store the statutory dates.

    Returns the schedule and whether it was written. A row whose dates were set
    by hand is left alone unless ``force`` is given: overwriting them silently
    would replace the dates the parties were working to with today's reading of
    the catalogue, which is the one thing a statutory date must not do.
    """
    schedule = build_schedule(
        regime,
        application_date=application.application_date,
        period_end=application.period_end,
        holidays=holidays,
    )
    if application.dates_overridden and not force:
        return schedule, False
    apply_schedule(application, schedule)
    application.dates_overridden = False
    await _repo_flush_application(session)
    return schedule, True


# ── Applications ─────────────────────────────────────────────────────────────


def _stated_dates(body: ApplicationCreate | ApplicationUpdate) -> dict[str, date]:
    """The statutory dates a caller stated explicitly, if any."""
    stated: dict[str, date] = {}
    for field in ("due_date", "payment_notice_deadline", "pay_less_deadline", "final_date"):
        value = getattr(body, field, None)
        if value is not None:
            stated[field] = value
    return stated


async def create_application(
    session: AsyncSession,
    *,
    body: ApplicationCreate,
    regime: PaymentRegime,
    created_by: str | None = None,
) -> StatutoryPaymentApplication:
    """Open a payment clock over an application.

    The dates are computed from the regime and then overwritten by any the
    caller stated, which is how a contract with its own compliant periods is
    recorded. Stating even one of them marks the row overridden so the
    recompute will not quietly take them back.
    """
    application = StatutoryPaymentApplication(
        project_id=body.project_id,
        regime_id=regime.id,
        source_type=body.source_type,
        source_id=body.source_id,
        reference=body.reference,
        application_date=body.application_date,
        period_start=body.period_start,
        period_end=body.period_end,
        applied_amount=body.applied_amount,
        currency=body.currency,
        status=body.status,
        paid_at=body.paid_at,
        paid_amount=body.paid_amount,
        notes=body.notes,
        created_by=created_by,
    )
    apply_schedule(
        application,
        build_schedule(
            regime,
            application_date=body.application_date,
            period_end=body.period_end,
            holidays=body.holidays,
        ),
    )
    stated = _stated_dates(body)
    for field, value in stated.items():
        setattr(application, field, value)
    application.dates_overridden = bool(stated)
    await _repo_add_application(session, application)
    return application


async def update_application(
    session: AsyncSession,
    *,
    application: StatutoryPaymentApplication,
    body: ApplicationUpdate,
) -> StatutoryPaymentApplication:
    """Apply the fields the caller actually sent. Does not recompute dates.

    Changing the application date moves every statutory date with it, but the
    recompute is a separate call on purpose: it is the action that overwrites
    evidence, and it says so in its own audit line rather than riding along
    with an edit to a reference number.
    """
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(application, field, value)
    if any(field in changes for field in ("due_date", "payment_notice_deadline", "pay_less_deadline", "final_date")):
        application.dates_overridden = True
    await _repo_flush_application(session)
    return application


async def delete_application(session: AsyncSession, *, application: StatutoryPaymentApplication) -> None:
    """Delete a clock. Its notices and events cascade in the database."""
    await _repo_remove_application(session, application)


# ── Notices ──────────────────────────────────────────────────────────────────


async def create_notice(
    session: AsyncSession,
    *,
    application: StatutoryPaymentApplication,
    body: NoticeCreate,
    created_by: str | None = None,
) -> PaymentNotice:
    """Record a notice that was served.

    A notice is recorded whether or not it was valid. Refusing to store a late
    or unsupported notice would delete the evidence that the rules exist to
    report on, so the row goes in and the findings say what is wrong with it.
    """
    notice = PaymentNotice(
        application_id=application.id,
        notice_type=body.notice_type,
        issued_at=body.issued_at,
        notified_amount=body.notified_amount,
        currency=body.currency or application.currency,
        basis_of_calculation=body.basis_of_calculation,
        served_by=body.served_by,
        served_to=body.served_to,
        reference=body.reference,
        created_by=created_by,
    )
    await _repo_add_notice(session, notice)
    return notice


async def delete_notice(session: AsyncSession, *, notice: PaymentNotice) -> None:
    """Delete a notice that was recorded in error."""
    await _repo_remove_notice(session, notice)


# ── The snapshot the rules read ──────────────────────────────────────────────


def notice_spec(notice: PaymentNotice) -> dict[str, Any]:
    """One notice as a plain dict, dates as ISO strings and money as strings."""
    return {
        "id": str(notice.id),
        "notice_type": notice.notice_type,
        "issued_at": notice.issued_at.isoformat() if notice.issued_at else None,
        "notified_amount": format(notice.notified_amount, "f") if notice.notified_amount is not None else None,
        "currency": notice.currency,
        "basis_of_calculation": notice.basis_of_calculation,
        "served_by": notice.served_by,
        "served_to": notice.served_to,
        "reference": notice.reference,
    }


def application_spec(application: StatutoryPaymentApplication) -> dict[str, Any]:
    """One application as a plain dict, in the shape the rules read."""
    return {
        "id": str(application.id),
        "project_id": str(application.project_id),
        "reference": application.reference,
        "source_type": application.source_type,
        "application_date": application.application_date.isoformat() if application.application_date else None,
        "period_start": application.period_start.isoformat() if application.period_start else None,
        "period_end": application.period_end.isoformat() if application.period_end else None,
        "applied_amount": format(application.applied_amount, "f") if application.applied_amount is not None else None,
        "currency": application.currency,
        "due_date": application.due_date.isoformat() if application.due_date else None,
        "payment_notice_deadline": (
            application.payment_notice_deadline.isoformat() if application.payment_notice_deadline else None
        ),
        "pay_less_deadline": application.pay_less_deadline.isoformat() if application.pay_less_deadline else None,
        "final_date": application.final_date.isoformat() if application.final_date else None,
        "dates_overridden": application.dates_overridden,
        "status": application.status,
        "paid_at": application.paid_at.isoformat() if application.paid_at else None,
        "paid_amount": format(application.paid_amount, "f") if application.paid_amount is not None else None,
    }


def clock_snapshot(
    application: StatutoryPaymentApplication,
    regime: PaymentRegime,
    notices: Sequence[PaymentNotice],
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Everything the rules need about one clock, as plain JSON-safe data.

    ``as_of`` is the date the clock is being read on. It is an argument rather
    than a call to ``date.today()`` inside the rules so a report can be run as
    at a past date, and so the tests are not hostages to the machine clock.
    """
    return {
        "as_of": (as_of or date.today()).isoformat(),
        "application": application_spec(application),
        "regime": regime_spec(regime),
        "notices": [notice_spec(notice) for notice in notices],
    }


# ── The notified sum ─────────────────────────────────────────────────────────


def notified_sum(
    application: StatutoryPaymentApplication,
    regime: PaymentRegime,
    notices: Sequence[PaymentNotice],
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """The sum that is actually payable, and the reason it is that sum.

    Four answers are possible and they are not the same statement:

    * the payer served a payment notice in time, so its sum is the notified sum;
    * the payer served none and the window has closed, so under a regime where
      silence concedes the claim the sum applied for is the notified sum - this
      is the rule the module exists for;
    * a payee's default payment notice supplies the sum where one was served;
    * the window is still open, or the regime attaches some other consequence
      to silence, so the sum is not yet settled and saying otherwise would be
      an invention.

    A pay-less notice never appears here. It reduces the sum that has to be
    *paid* on the final date; it does not displace the notified sum, and
    conflating the two is the mistake that loses the adjudication.

    Each answer carries ``reason`` and ``params`` beside ``explanation``. The
    prose is the API's answer and stays; the code and its parameters are what a
    screen needs to say the same thing in the reader's language, because a
    sentence assembled here can only ever be assembled in one. ``source`` does
    not serve: three different answers share ``undetermined`` and they are
    different statements.
    """
    today = as_of or date.today()
    currency = application.currency
    deadline = application.payment_notice_deadline

    in_time = [
        notice
        for notice in notices
        if notice.notice_type == "payment_notice" and (deadline is None or notice.issued_at <= deadline)
    ]
    if in_time:
        chosen = max(in_time, key=lambda notice: notice.issued_at)
        return {
            "amount": chosen.notified_amount,
            "currency": chosen.currency or currency,
            "source": "payment_notice",
            "reason": "payment_notice",
            "params": {
                "issued": chosen.issued_at.isoformat(),
                "amount": format_money(chosen.notified_amount, chosen.currency or currency),
            },
            "explanation": (
                f"A payment notice served on {chosen.issued_at.isoformat()} states "
                f"{format_money(chosen.notified_amount, chosen.currency or currency)}."
            ),
        }

    if deadline is None and regime.no_notice_effect == "none":
        # The EU Directive and the German regimes have no notice sequence at
        # all, so there is no window to call open: no notice could ever fix the
        # sum, and saying "the window is still open" would promise a settling
        # event that will never arrive.
        return {
            "amount": None,
            "currency": currency,
            "source": "undetermined",
            "reason": "no_notice_sequence",
            "params": {"statute": regime.statute},
            "explanation": (
                f"{regime.statute} provides no payment notice sequence: it fixes the period for payment "
                "and the interest that runs when it is missed, and no notice can settle the sum payable. "
                "The sum applied for stands unless the payer disputes it."
            ),
        }

    if deadline is None or today <= deadline:
        return {
            "amount": None,
            "currency": currency,
            "source": "undetermined",
            # Two sentences, not one with an optional tail: a language that puts
            # the date first cannot reorder a clause glued on after the fact.
            "reason": "window_open_until" if deadline else "window_open",
            "params": {"deadline": deadline.isoformat()} if deadline else {},
            "explanation": (
                "No payment notice has been served yet and the window is still open"
                + (f" until {deadline.isoformat()}." if deadline else " under this regime.")
            ),
        }

    if regime.no_notice_effect != "applied_sum_becomes_notified_sum":
        return {
            "amount": None,
            "currency": currency,
            "source": "undetermined",
            "reason": "silence_does_not_fix",
            "params": {"deadline": deadline.isoformat(), "statute": regime.statute},
            "explanation": (
                f"No payment notice was served by {deadline.isoformat()}. Under {regime.statute} that does "
                "not by itself fix the sum payable, so the amount remains in dispute."
            ),
        }

    default_notices = [notice for notice in notices if notice.notice_type == "default_payment_notice"]
    if default_notices:
        chosen = max(default_notices, key=lambda notice: notice.issued_at)
        return {
            "amount": chosen.notified_amount if chosen.notified_amount is not None else application.applied_amount,
            "currency": chosen.currency or currency,
            "source": "default_payment_notice",
            "reason": "default_payment_notice",
            "params": {
                "deadline": deadline.isoformat(),
                "issued": chosen.issued_at.isoformat(),
                "statute": regime.statute,
            },
            "explanation": (
                f"No payment notice was served by {deadline.isoformat()}, and the payee's default payment "
                f"notice of {chosen.issued_at.isoformat()} states the sum due under {regime.statute}."
            ),
        }

    return {
        "amount": application.applied_amount,
        "currency": currency,
        "source": "application",
        "reason": "application",
        "params": {
            "deadline": deadline.isoformat(),
            "statute": regime.statute,
            "amount": format_money(application.applied_amount, currency),
        },
        "explanation": (
            f"No payment notice was served by {deadline.isoformat()}, so under {regime.statute} the sum "
            f"applied for, {format_money(application.applied_amount, currency)}, is the notified sum and is "
            "payable in full by the final date for payment."
        ),
    }


# ── The breach register ──────────────────────────────────────────────────────


def _event_key(event_type: str, element_ref: str) -> tuple[str, str]:
    return (event_type, element_ref)


def _finding_amount(details: dict[str, Any]) -> Decimal | None:
    for key in ("applied_amount", "outstanding_amount", "amount"):
        amount = parse_money(details.get(key))
        if amount is not None:
            return amount
    return None


def _finding_date(details: dict[str, Any]) -> date | None:
    for key in ("deadline", "final_date", "due_date"):
        value = parse_date(details.get(key))
        if value is not None:
            return value
    return None


def _finding_days(details: dict[str, Any]) -> int | None:
    for key in ("days_late", "days_overdue"):
        value = details.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


async def record_clock_events(
    session: AsyncSession,
    *,
    application: StatutoryPaymentApplication,
    findings: Sequence[Any],
) -> list[PaymentClockEvent]:
    """Bring the breach register in line with the current findings.

    An existing event for the same rule and the same subject is updated in
    place so ``detected_at`` keeps saying when the breach was first seen, which
    is the date interest and time bars are argued from. An event whose finding
    no longer appears is deleted: it was a data-entry mistake that has since
    been corrected, and a register carrying breaches that did not happen stops
    being read.

    Matching is done in Python over the rows already loaded, not with a filter
    inside the JSON column. ``.contains()`` on a JSON column compiles to a
    string LIKE rather than to JSONB containment, so a query written that way
    would quietly mean something else.
    """
    existing = await _repo_list_events_for_application(session, application_id=application.id)
    by_key: dict[tuple[str, str], PaymentClockEvent] = {}
    for event in existing:
        detail = event.detail if isinstance(event.detail, dict) else {}
        by_key[_event_key(event.event_type, str(detail.get("element_ref") or ""))] = event

    now = datetime.now(UTC)
    kept: set[tuple[str, str]] = set()
    written: list[PaymentClockEvent] = []

    for finding in findings:
        event_type = RULE_EVENT_TYPES.get(finding.rule_id)
        if event_type is None:
            # A finding worth showing that is not worth filing - a currency
            # mismatch is a note on the screen, not a breach of the statute.
            continue
        details = dict(finding.details or {})
        element_ref = str(finding.element_ref or "")
        key = _event_key(event_type, element_ref)
        kept.add(key)
        detail_payload = {**details, "element_ref": element_ref, "suggestion": finding.suggestion or ""}
        event = by_key.get(key)
        if event is None:
            event = PaymentClockEvent(application_id=application.id, event_type=event_type, detected_at=now)
            await _repo_add_event(session, event)
        event.severity = str(finding.severity)
        event.rule_id = finding.rule_id
        event.deadline_date = _finding_date(details)
        event.days_late = _finding_days(details)
        event.amount = _finding_amount(details)
        event.currency = str(details.get("currency") or application.currency or "")
        event.consequence = finding.message
        event.detail = detail_payload
        written.append(event)

    stale = [event.id for key, event in by_key.items() if key not in kept]
    await _repo_delete_stale_events(session, stale)
    await _repo_flush_events(session)
    return written


def regime_summary(regime: PaymentRegime) -> str:
    """The interest clause of a regime as one sentence, for a response body."""
    return interest_description(regime_spec(regime))


__all__ = [
    "TERMINAL_STATUSES",
    "application_spec",
    "apply_schedule",
    "build_schedule",
    "clock_snapshot",
    "create_application",
    "create_notice",
    "delete_application",
    "delete_notice",
    "ensure_regimes",
    "get_application",
    "get_notice",
    "get_regime",
    "get_regime_by_code",
    "list_applications",
    "list_events",
    "list_notices",
    "list_regimes",
    "notice_spec",
    "notified_sum",
    "record_clock_events",
    "recompute_schedule",
    "regime_spec",
    "regime_summary",
    "update_application",
]
