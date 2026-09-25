# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure completeness and arithmetic checks for a subcontract agreement.

Validation is first-class for this module (platform principle #4). A
subcontract agreement leaving ``draft`` for ``active`` is the moment a
subcontractor may start work, raise payment applications against the scope and
accrue retention. Everything downstream reads the agreement rather than
re-deriving it: :meth:`SubcontractorService.sov_summary` divides by the
agreement's ``total_value``, :meth:`accrue_retention` multiplies by its
``retention_percent``, and the payment-application chain settles in its
``currency``. An agreement that goes live with a zero value, a blank currency
or work packages worth more than the contract produces reports nobody can
reconcile, and the error surfaces weeks later inside a payment claim.

Like ``procurement/validators.py`` this module is deliberately
**dependency-free**: standard library plus :class:`~decimal.Decimal`, no ORM,
no FastAPI, no session. The rule classes in ``app.core.validation.rules`` stay
thin wrappers translating a :class:`Finding` into a ``RuleResult``, so the
checks themselves are unit-testable without a database.

Payload shape
-------------
The service flattens an agreement, its work packages and the parts of the
subcontractor row these checks need into one dict. Money arrives as Decimal
strings and dates as ``YYYY-MM-DD`` strings, both parsed here rather than by
the caller.

The clock is data, never ``date.today()``
-----------------------------------------
Every date-relative check reads :data:`AS_OF_KEY` from the payload. The service
fills it with today's date; a test passes it explicitly. A rule that asks the
system clock what day it is cannot be pinned by a test that still passes next
year, so no check in this module calls ``today()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

# The one spelling an amount gets anywhere in this platform. It lives in its own
# module precisely so that this file can keep the standard-library-only contract
# its docstring declares: the same function is what the core validation rules
# call, and a second spelling here would disagree with them on every currency
# that does not have two decimals.
from app.core.currency_registry import sentence_amount

#: Payload key carrying the date the checks should consider "now". The service
#: fills it; tests set it explicitly so date-relative rules stay deterministic.
AS_OF_KEY = "as_of"

#: Amounts closer than this are equal, matching the procurement tolerance.
MONEY_TOLERANCE = Decimal("0.01")

#: Retention above this is a data-entry error rather than retention. The
#: construction norm is 5-10%; past half the contract it is not a holdback.
MAX_SANE_RETENTION_PERCENT = Decimal("50")


@dataclass(frozen=True)
class Finding:
    """One failed check on one element.

    :param element_ref: what the user should look at -- a work-package name or
        the agreement title. Never ``None``: a finding the UI cannot anchor is
        a finding the user cannot act on.
    :param params: placeholders for the translated message, pre-formatted as
        strings so the message layer never formats money or dates itself.
    :param details: machine-readable context for the report payload.
    """

    element_ref: str
    params: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def parse_money(raw: Any) -> Decimal | None:
    """Parse a Decimal-string amount, or ``None`` when it is not a number.

    Returning ``None`` rather than raising is deliberate: an unparseable amount
    is itself a finding, and the caller decides how to report it.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(raw: Any) -> Decimal:
    """Parse an amount, treating anything unparseable as zero."""
    parsed = parse_money(raw)
    return parsed if parsed is not None else Decimal("0")


def _fmt(value: Decimal) -> str:
    """Render a *percentage* for a user-facing message, two decimals, no exponent.

    Not for money, despite the name it has always had. Money goes through
    :func:`_amount`, which asks the currency how many decimals it keeps and
    writes the code beside the digits. The retention template glues ``%`` onto
    its slot, so an amount rendered through this function would read
    ``50.00 EUR%``, and grouping a percentage gains a reader nothing.
    """
    return f"{value.quantize(Decimal('0.01')):f}"


def _currency(agreement: dict[str, Any]) -> str:
    """The code this agreement states, never a default.

    Blank stays blank: the renderer then groups the digits and writes no code.
    :func:`check_currency_set` is the rule that complains about a missing
    currency, so nothing is lost by declining to guess one here, and a guessed
    code would read as authoritative and be wrong whenever the project is not in
    it.
    """
    return str(agreement.get("currency") or "").strip()


def _amount(value: Decimal, agreement: dict[str, Any]) -> str:
    """Render an amount for a message, in the agreement's own currency."""
    return sentence_amount(value, _currency(agreement))


def parse_date(raw: Any) -> date | None:
    """Parse the leading ``YYYY-MM-DD`` of a date value, or ``None``.

    Anything that is not an ISO date is treated as absent rather than as a
    finding: these checks are about ordering and expiry, not about format, and
    the columns are already typed as ``Date`` at the database level.
    """
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_of(agreement: dict[str, Any]) -> date | None:
    """The date the checks treat as today, or ``None`` when the caller omitted it."""
    return parse_date(agreement.get(AS_OF_KEY))


def _packages(agreement: dict[str, Any]) -> list[dict[str, Any]]:
    packages = agreement.get("work_packages")
    return [p for p in packages if isinstance(p, dict)] if isinstance(packages, list) else []


def _agreement_ref(agreement: dict[str, Any]) -> str:
    return str(agreement.get("title") or agreement.get("id") or "?")


def package_label(index: int, package: dict[str, Any]) -> str:
    """A human work-package label: the 1-based row number plus a trimmed name."""
    name = str(package.get("name") or "").strip()
    if not name:
        return str(index + 1)
    if len(name) > 40:
        name = name[:37] + "..."
    return f"{index + 1} ({name})"


# ── Checks ───────────────────────────────────────────────────────────────────


def check_has_scope(agreement: dict[str, Any]) -> list[Finding]:
    """An agreement going live must break its scope into work packages.

    Without them there is nothing for a payment application to claim against:
    every payment line carries a ``work_package_id``, so an active agreement
    with no packages can only ever be paid against nothing, and the schedule of
    values reports a contract value with no lines under it.
    """
    if _packages(agreement):
        return []
    return [Finding(element_ref=_agreement_ref(agreement), details={"work_package_count": 0})]


def check_package_scope_described(agreement: dict[str, Any]) -> list[Finding]:
    """Each work package should say what the work actually is.

    A named package with no scope text is the classic source of a variation
    argument: both sides agreed on a title and neither wrote down what it
    covers. WARNING rather than ERROR -- the scope often lives in an attached
    specification during the first weeks of a contract.
    """
    findings: list[Finding] = []
    for index, package in enumerate(_packages(agreement)):
        if not str(package.get("scope") or "").strip():
            findings.append(
                Finding(
                    element_ref=package_label(index, package),
                    params={"package": package_label(index, package)},
                    details={"scope": None},
                )
            )
    return findings


def check_value_positive(agreement: dict[str, Any]) -> list[Finding]:
    """The contract value must be greater than zero.

    Retention is a percentage of it and the schedule of values divides by it, so
    a zero-value active agreement makes both meaningless and any percent-complete
    figure derived from it is a division by zero the reporting layer has to hide.
    """
    total = parse_money(agreement.get("total_value"))
    if total is None:
        return [
            Finding(
                element_ref=_agreement_ref(agreement),
                params={"value": "?"},
                details={"reason": "unparseable_total_value"},
            )
        ]
    if total > 0:
        return []
    return [
        Finding(
            element_ref=_agreement_ref(agreement),
            params={"value": _amount(total, agreement)},
            details={"total_value": str(total)},
        )
    ]


def check_packages_within_value(agreement: dict[str, Any]) -> list[Finding]:
    """The work packages must not be worth more than the contract itself.

    Packages priced above ``total_value`` mean the agreement is under-funded on
    the day it goes live: the sum of what the subcontractor may legitimately
    claim already exceeds what was contracted, and the overrun only becomes
    visible once claims start arriving.

    Skipped when there are no packages -- :func:`check_has_scope` already owns
    that case and reporting it twice would double-count one problem.
    """
    packages = _packages(agreement)
    if not packages:
        return []
    planned = sum((_money(p.get("planned_value")) for p in packages), Decimal("0"))
    total = _money(agreement.get("total_value"))
    if planned - total <= MONEY_TOLERANCE:
        return []
    return [
        Finding(
            element_ref=_agreement_ref(agreement),
            params={"planned": _amount(planned, agreement), "total": _amount(total, agreement)},
            details={"planned_value_sum": str(planned), "total_value": str(total)},
        )
    ]


def check_dates_ordered(agreement: dict[str, Any]) -> list[Finding]:
    """The contract cannot end before it starts."""
    start = parse_date(agreement.get("start_date"))
    end = parse_date(agreement.get("end_date"))
    if start is None or end is None or end >= start:
        return []
    return [
        Finding(
            element_ref=_agreement_ref(agreement),
            params={"start": start.isoformat(), "end": end.isoformat()},
            details={"start_date": start.isoformat(), "end_date": end.isoformat()},
        )
    ]


def check_currency_set(agreement: dict[str, Any]) -> list[Finding]:
    """The agreement must carry a currency.

    The column's server default is an empty string, so a blank value here means
    nothing ever set it. Every payment application under the agreement inherits
    that currency, and an amount without one cannot be rolled up or paid.
    """
    if str(agreement.get("currency") or "").strip():
        return []
    return [Finding(element_ref=_agreement_ref(agreement), details={"currency": ""})]


def check_retention_within_bounds(agreement: dict[str, Any]) -> list[Finding]:
    """Retention must be a percentage, and a plausible one.

    ``accrue_retention`` multiplies each payment by this number, so a rate typed
    as an amount withholds a fortune from the first claim.
    """
    percent = parse_money(agreement.get("retention_percent"))
    if percent is None:
        return [
            Finding(
                element_ref=_agreement_ref(agreement),
                params={"percent": "?", "max": _fmt(MAX_SANE_RETENTION_PERCENT)},
                details={"reason": "unparseable_percent"},
            )
        ]
    if Decimal("0") <= percent <= MAX_SANE_RETENTION_PERCENT:
        return []
    return [
        Finding(
            element_ref=_agreement_ref(agreement),
            params={"percent": _fmt(percent), "max": _fmt(MAX_SANE_RETENTION_PERCENT)},
            details={"retention_percent": str(percent), "max": str(MAX_SANE_RETENTION_PERCENT)},
        )
    ]


def check_insurance_valid_at_start(agreement: dict[str, Any]) -> list[Finding]:
    """The subcontractor's insurance must still be valid when work starts.

    Letting an uninsured subcontractor on site is the exposure the module's own
    ``flag_expiring_insurance`` sweep exists to prevent, and activation is the
    last moment anyone looks before the work begins.

    Compared against the agreement's ``start_date`` when it has one, otherwise
    against :data:`AS_OF_KEY`. An unknown expiry date produces no finding: the
    column is nullable and a missing certificate is the certificate register's
    problem, not a reason to call a known-good date expired.
    """
    expiry = parse_date(agreement.get("insurance_expiry_date"))
    if expiry is None:
        return []
    reference = parse_date(agreement.get("start_date")) or _as_of(agreement)
    if reference is None or expiry >= reference:
        return []
    return [
        Finding(
            element_ref=_agreement_ref(agreement),
            params={"expiry": expiry.isoformat(), "reference": reference.isoformat()},
            details={
                "insurance_expiry_date": expiry.isoformat(),
                "reference_date": reference.isoformat(),
            },
        )
    ]


# ── GC claim rollup checks ───────────────────────────────────────────────────
#
# These read the subcontract rollup of one GC progress claim, the plain dict
# :func:`app.modules.subcontractors.rollup.rule_context_from_rollup` builds and
# the contracts module places under ``subcontract_rollup`` in the claim's rule
# context. They answer what a lender's draw inspector asks before funding a
# monthly bill: are the subcontract amounts the GC is billing approved, waived
# and insured, and do they land on the GC's own schedule of values.
#
# Every check takes the rollup dict itself. An absent or malformed rollup is
# not a rollup with problems in it: the caller has no subcontract data to judge
# (a project without subcontractors, or a rollup that failed to load), and each
# check returns nothing rather than inventing a missing waiver. The rule
# wrappers depend on that, because two of these are errors and an error blocks
# the claim's submission.

#: Payment statuses at which the GC has approved a pay application for payment.
#: A pay application still ``submitted`` has been received and nothing more.
_APPROVED_PAY_APP_STATUSES = frozenset({"foreman_approved", "finance_approved", "paid"})


def _rollup_rows(rollup: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = rollup.get(key) if isinstance(rollup, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _pay_app_ref(row: dict[str, Any]) -> str:
    """How a finding names a pay application: its number and whose it is."""
    number = str(row.get("application_number") or row.get("payment_application_id") or "?")
    name = str(row.get("subcontractor_name") or "").strip()
    return f"{number} ({name})" if name else number


def _currency_of(rollup: dict[str, Any]) -> str:
    return str(rollup.get("currency") or "").strip()


def check_sub_unapproved_included(rollup: dict[str, Any]) -> list[Finding]:
    """An included pay application must have been approved by the GC.

    Billing the owner for subcontract work the GC has not itself approved puts
    an unverified amount on a certified payment application. ``submitted``
    means received and unreviewed; ``rejected`` means reviewed and refused,
    which is worse, and both are reported with their status.
    """
    findings: list[Finding] = []
    for row in _rollup_rows(rollup, "included"):
        status = str(row.get("status") or "")
        if status in _APPROVED_PAY_APP_STATUSES:
            continue
        findings.append(
            Finding(
                element_ref=_pay_app_ref(row),
                params={"pay_app": _pay_app_ref(row), "status": status or "?"},
                details={"payment_application_id": row.get("payment_application_id"), "status": status},
            )
        )
    return findings


def _waiver_covers_period(row: dict[str, Any]) -> bool:
    """Whether the waivers on file cover this pay application's net and period.

    The amount test is the payment gate's own (largest waiver at least the
    net). The period test is new with the through-date: a waiver whose
    through-date ends before the pay application's period end does not release
    the last days of the work being paid. Either date unknown asks nothing.
    """
    waiver = row.get("waiver") if isinstance(row.get("waiver"), dict) else {}
    if not waiver.get("covers_net"):
        return False
    through = parse_date(waiver.get("through_date"))
    period_end = parse_date(row.get("period_end"))
    return through is None or period_end is None or through >= period_end


def check_sub_waiver_missing(rollup: dict[str, Any]) -> list[Finding]:
    """An included pay application needs a lien waiver covering what is paid.

    Required by the agreement (``requires_lien_waiver``), the finding is an
    error: the module's own payment gate would refuse to pay without it, so the
    GC would be billing the owner for money it cannot release. Required only by
    the national pack, it is a warning: the practice expects one, the contract
    does not. Required by neither, nothing is checked.

    ``details["severity"]`` carries which of the two applies, so the rule can
    report each finding at its own severity.
    """
    pack_requires = bool(rollup.get("pack_requires_lien_waiver")) if isinstance(rollup, dict) else False
    findings: list[Finding] = []
    for row in _rollup_rows(rollup, "included"):
        agreement_requires = bool(row.get("requires_lien_waiver"))
        if not agreement_requires and not pack_requires:
            continue
        if _waiver_covers_period(row):
            continue
        waiver = row.get("waiver") if isinstance(row.get("waiver"), dict) else {}
        net = _money(row.get("net_amount"))
        covered = _money(waiver.get("amount_covered"))
        # Which half failed decides what the person has to fetch: a waiver for
        # more money, or one signed through a later date. The amount is asked
        # first because a short waiver is short whatever its date says.
        reason = "through_date" if waiver.get("covers_net") else "amount"
        findings.append(
            Finding(
                element_ref=_pay_app_ref(row),
                params={
                    "pay_app": _pay_app_ref(row),
                    "net": sentence_amount(net, _currency_of(rollup)),
                    "covered": sentence_amount(covered, _currency_of(rollup)),
                    "through_date": str(waiver.get("through_date") or "?"),
                    "period_end": str(row.get("period_end") or "?"),
                },
                details={
                    "payment_application_id": row.get("payment_application_id"),
                    "severity": "error" if agreement_requires else "warning",
                    "reason": reason,
                    "waiver_state": waiver.get("state") or "none",
                    "net_amount": str(net),
                    "amount_covered": str(covered),
                    "through_date": waiver.get("through_date"),
                    "period_end": row.get("period_end"),
                },
            )
        )
    return findings


def check_sub_prior_unconditional_missing(rollup: dict[str, Any]) -> list[Finding]:
    """A sub paid on an earlier claim should have released that work unconditionally.

    Lender practice on a monthly draw: the conditional waiver that came with
    last month's pay application becomes an unconditional one once the money
    has actually been paid, and it has to run through the end of the period
    that payment covered. A paid pay application without one is a lien right
    the owner's title is still exposed to.
    """
    findings: list[Finding] = []
    for row in _rollup_rows(rollup, "prior_paid"):
        through = parse_date(row.get("unconditional_through"))
        period_end = parse_date(row.get("period_end"))
        if through is not None and (period_end is None or through >= period_end):
            continue
        findings.append(
            Finding(
                element_ref=_pay_app_ref(row),
                params={
                    "pay_app": _pay_app_ref(row),
                    "period_end": period_end.isoformat() if period_end else "?",
                },
                details={
                    "payment_application_id": row.get("payment_application_id"),
                    "unconditional_through": through.isoformat() if through else None,
                    "period_end": period_end.isoformat() if period_end else None,
                },
            )
        )
    return findings


def check_sub_line_unmapped(rollup: dict[str, Any]) -> list[Finding]:
    """Every included subcontract line must land on a billable GC line.

    An unmapped line is subcontract cost the GC is paying that the owner's
    schedule of values cannot show, so the monthly bill and the sub ledger stop
    reconciling. It is reported, never guessed onto a line.
    """
    findings: list[Finding] = []
    for row in _rollup_rows(rollup, "unmapped_lines"):
        amount = _money(row.get("approved_amount"))
        findings.append(
            Finding(
                element_ref=_pay_app_ref(row),
                params={
                    "pay_app": _pay_app_ref(row),
                    "package": str(row.get("work_package_name") or "?"),
                    "amount": sentence_amount(amount, _currency_of(rollup)),
                },
                details={
                    "payment_application_id": row.get("payment_application_id"),
                    "line_id": row.get("line_id"),
                    "reason": row.get("reason") or "none",
                },
            )
        )
    return findings


def check_sub_exceeds_gc_line(rollup: dict[str, Any]) -> list[Finding]:
    """Subcontract approved to date must not exceed the GC's scheduled value.

    The GC cannot bill more than the line's scheduled value, so subcontract
    approvals above it are paid out of the GC's own margin or a change order
    nobody has written yet. The subcontract side is kept to two decimals and
    the GC side to four, so a difference inside the money tolerance is
    rounding, not an overrun.
    """
    findings: list[Finding] = []
    for row in _rollup_rows(rollup, "lines"):
        approved = _money(row.get("sub_approved_to_date"))
        scheduled = _money(row.get("scheduled_value"))
        if approved - scheduled <= MONEY_TOLERANCE:
            continue
        label = str(row.get("code") or row.get("contract_line_id") or "?")
        findings.append(
            Finding(
                element_ref=label,
                params={
                    "line": label,
                    "approved": sentence_amount(approved, _currency_of(rollup)),
                    "scheduled": sentence_amount(scheduled, _currency_of(rollup)),
                },
                details={
                    "contract_line_id": row.get("contract_line_id"),
                    "sub_approved_to_date": str(approved),
                    "scheduled_value": str(scheduled),
                },
            )
        )
    return findings


def check_sub_certificate_lapsed(rollup: dict[str, Any]) -> list[Finding]:
    """Each included sub must hold its required certificates through the period end.

    Judged as at the claim's period end, never today: a claim for last month is
    about whether the sub was insured last month, and asking the clock would
    both flag a certificate that lapsed since and pass one that was renewed
    late. A claim with no period end yet has no date to judge on, so this check
    says nothing about it rather than falling back to today.

    One finding per subcontractor and document, however many of that sub's pay
    applications are in the claim.
    """
    if not isinstance(rollup, dict) or parse_date(rollup.get(AS_OF_KEY)) is None:
        return []
    as_of = parse_date(rollup.get(AS_OF_KEY))
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for row in _rollup_rows(rollup, "included"):
        subcontractor = str(row.get("subcontractor_id") or row.get("subcontractor_name") or "")
        for problem in row.get("certificate_findings") or []:
            if not isinstance(problem, dict):
                continue
            document = str(problem.get("document_type") or "?")
            key = (subcontractor, document)
            if key in seen:
                continue
            seen.add(key)
            lapsed = parse_date(problem.get("lapsed_on"))
            name = str(row.get("subcontractor_name") or "").strip() or "?"
            findings.append(
                Finding(
                    element_ref=name,
                    params={
                        "subcontractor": name,
                        "document": document,
                        "state": str(problem.get("state") or "missing"),
                        "as_of": as_of.isoformat() if as_of else "?",
                    },
                    details={
                        "subcontractor_id": row.get("subcontractor_id"),
                        "document_type": document,
                        "state": problem.get("state"),
                        "lapsed_on": lapsed.isoformat() if lapsed else None,
                        "as_of": as_of.isoformat() if as_of else None,
                    },
                )
            )
    return findings


#: Payment-date states of a pay application that is not paid yet. Only
#: ``pending`` and ``pending_open`` are notes; ``pending_invalid`` already knows
#: that no certificate on file could cover the payment.
_PAYMENT_DATE_NOTE_STATES = frozenset({"pending", "pending_open"})

#: Every state the payment-date check words. Anything else is worded as missing.
PAYMENT_DATE_STATES = ("missing", "expired", "revoked", "undated", "pending", "pending_open", "pending_invalid")


def check_sub_certificate_payment_date(rollup: dict[str, Any]) -> list[Finding]:
    """A certificate the law reads on the payment day must be valid on that day.

    For these certificates the period end says nothing: a German exemption
    certificate valid on the last day of March and expired on the day the
    money went in May exempts nothing, and the payer owes the withholding.
    So each included pay application is read on its own payment day, one
    finding per pay application and document, because two payments to the
    same sub fall on two different days.

    Nothing here blocks a submission and nothing is deducted. A paid pay
    application the certificate did not cover is a warning that names the
    withholding the law then requires. An unpaid one is not "met": its day has
    not come, so it is a note that says the certificate is read on the payment
    date, or a warning when nothing on file could cover that date.
    ``details["severity"]`` carries which.
    """
    findings: list[Finding] = []
    for row in _rollup_rows(rollup, "included"):
        for problem in row.get("payment_date_findings") or []:
            if not isinstance(problem, dict):
                continue
            document = str(problem.get("document_type") or "?")
            state = str(problem.get("state") or "missing")
            if state not in PAYMENT_DATE_STATES:
                state = "missing"
            judged_on = parse_date(problem.get("judged_on"))
            lapsed = parse_date(problem.get("lapsed_on"))
            valid_until = parse_date(problem.get("valid_until"))
            withholding = problem.get("withholding") if isinstance(problem.get("withholding"), dict) else None
            name = str(row.get("subcontractor_name") or "").strip() or "?"
            number = str(row.get("application_number") or row.get("payment_application_id") or "?")
            findings.append(
                Finding(
                    element_ref=_pay_app_ref(row),
                    params={
                        "subcontractor": name,
                        "pay_app": number,
                        "document": document,
                        "paid_on": judged_on.isoformat() if judged_on else "?",
                        "lapsed_on": lapsed.isoformat() if lapsed else "?",
                        "valid_until": valid_until.isoformat() if valid_until else "?",
                    },
                    details={
                        "payment_application_id": row.get("payment_application_id"),
                        "subcontractor_id": row.get("subcontractor_id"),
                        "document_type": document,
                        "state": state,
                        "severity": "info" if state in _PAYMENT_DATE_NOTE_STATES else "warning",
                        "paid_on": judged_on.isoformat() if judged_on else None,
                        "lapsed_on": lapsed.isoformat() if lapsed else None,
                        "valid_until": valid_until.isoformat() if valid_until else None,
                        "withholding": dict(withholding) if withholding else None,
                    },
                )
            )
    return findings


# ── One subcontract written twice ────────────────────────────────────────────
#
# A subcontract can be written as an agreement here and as a contract with a
# subcontractor in the contracts module. Linked through
# ``SubcontractAgreement.contract_id`` the pair counts once; unlinked, finance
# sees two commitments for one spend. Nothing in the data proves two unlinked
# records are the same subcontract, so they are never merged: a likely pair is
# reported and a person links it or says the two are different.

#: Statuses on either side that no longer commit anything.
_ENDED_STATUSES = frozenset({"terminated", "cancelled", "canceled", "void"})

#: Legal-form words dropped before names are compared, so "Suhi Zid d.o.o."
#: and "SUHI ZID" read as one company. Only whole tokens are dropped.
_LEGAL_FORMS = frozenset(
    {
        "ab", "ag", "as", "bv", "co", "company", "corp", "corporation", "doo", "dd", "eood", "gmbh", "inc",
        "kft", "kg", "llc", "llp", "ltd", "limited", "nv", "oy", "oo", "ooo", "plc", "pty", "sa", "sarl",
        "sas", "spa", "sp", "srl", "sro", "zoo",
    }
)  # fmt: skip


def normalise_company_name(raw: Any) -> str:
    """A company name reduced to what identifies it: letters and digits, no legal form.

    Case-folded, punctuation dropped, legal-form tokens removed. Returns ``""``
    when nothing identifying is left, and an empty name never matches.
    """
    text = str(raw or "").casefold()
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text.replace(".", ""))
    tokens = [token for token in cleaned.split() if token not in _LEGAL_FORMS]
    return " ".join(tokens)


def _identity(record: dict[str, Any]) -> tuple[set[str], set[str]]:
    ids = {str(v) for v in record.get("party_ids") or [] if v}
    names = {n for n in (normalise_company_name(v) for v in record.get("party_names") or []) if n}
    return ids, names


def _value_close(a: Any, b: Any) -> bool:
    """Within 1% of the larger value: a bonus signal, never required."""
    left, right = parse_money(a), parse_money(b)
    if left is None or right is None or left <= 0 or right <= 0:
        return False
    return abs(left - right) <= max(left, right) / Decimal("100")


def match_unlinked_twins(agreements: list[dict[str, Any]], contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pairs of an unlinked agreement and an unclaimed subcontract that look like one subcontract.

    ``agreements`` and ``contracts`` are flat dicts for one project:
    ``id``, ``status``, ``currency``, ``total_value``, ``party_ids`` (the ids
    the counterparty goes by: subcontractor and contact) and ``party_names``.
    An agreement also carries ``contract_id`` and ``dismissed_contract_ids``.

    A pair is reported when the agreement is not linked, no agreement links the
    contract, both are live, the currencies are the same and the counterparty
    is the same by id or by normalised company name. A close value is recorded
    as ``value_close`` and does not decide anything.
    """
    claimed = {str(a["contract_id"]) for a in agreements if a.get("contract_id")}
    open_contracts = [
        c for c in contracts if str(c.get("id")) not in claimed and str(c.get("status") or "") not in _ENDED_STATUSES
    ]
    pairs: list[dict[str, Any]] = []
    for agreement in agreements:
        if agreement.get("contract_id") or str(agreement.get("status") or "") in _ENDED_STATUSES:
            continue
        currency = str(agreement.get("currency") or "").strip().upper()
        if not currency:
            continue
        a_ids, a_names = _identity(agreement)
        dismissed = {str(v) for v in agreement.get("dismissed_contract_ids") or []}
        for contract in open_contracts:
            if str(contract.get("id")) in dismissed:
                continue
            if str(contract.get("currency") or "").strip().upper() != currency:
                continue
            c_ids, c_names = _identity(contract)
            by_id = bool(a_ids & c_ids)
            by_name = bool(a_names & c_names)
            if not (by_id or by_name):
                continue
            pairs.append(
                {
                    "agreement_id": str(agreement.get("id")),
                    "agreement_title": str(agreement.get("title") or ""),
                    "contract_id": str(contract.get("id")),
                    "contract_code": str(contract.get("code") or ""),
                    "contract_title": str(contract.get("title") or ""),
                    "currency": currency,
                    "agreement_value": str(agreement.get("total_value") or "0"),
                    "contract_value": str(contract.get("total_value") or "0"),
                    "matched_on": "counterparty" if by_id else "name",
                    "value_close": _value_close(agreement.get("total_value"), contract.get("total_value")),
                }
            )
    return pairs


def check_unlinked_contract_twin(agreement: dict[str, Any]) -> list[Finding]:
    """This agreement looks like a subcontract also written, unlinked, in contracts.

    Reads ``twin_candidates``, the pairs :func:`match_unlinked_twins` found for
    this agreement, which the service fills. One finding per contract.
    """
    candidates = agreement.get("twin_candidates")
    if not isinstance(candidates, list):
        return []
    findings: list[Finding] = []
    for pair in candidates:
        if not isinstance(pair, dict):
            continue
        contract = " ".join(p for p in (pair.get("contract_code"), pair.get("contract_title")) if p) or "?"
        findings.append(
            Finding(
                element_ref=_agreement_ref(agreement),
                params={"agreement": _agreement_ref(agreement), "contract": contract},
                details={
                    "contract_id": pair.get("contract_id"),
                    "matched_on": pair.get("matched_on"),
                    "value_close": bool(pair.get("value_close")),
                },
            )
        )
    return findings
