# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure completeness and comparability checks for an RFQ and its bids.

Validation is first-class for this module (platform principle #4). An RFQ has
two moments that cannot be taken back. Publishing sends the package to vendors,
who then spend real estimating hours on it; a package that was unpriceable or
already closed wastes their time and returns nothing usable. Awarding turns one
of the returned numbers into the basis of a purchase order or a subcontract,
which means the comparison that picked it has to have been a comparison of like
with like.

The two moments ask different questions, so they are two rule sets:

``rfq_issue``
    Everything a vendor needs in order to bid at all, including whether the
    submission deadline is still in the future. Run from
    :meth:`RFQService.issue_rfq`.

``rfq_award``
    Everything the comparison between bids relies on. Run from
    :meth:`RFQService.award_bid`. The deadline-in-the-future check is
    deliberately absent here: by award time the deadline has passed on purpose,
    and a rule that failed for that reason would fail every award forever.

Splitting the sets rather than passing an ``operation`` flag into the payload is
deliberate. A rule whose behaviour depends on a string the caller supplies is
the same hazard as a rule registered into a set nobody calls: it is reachable on
paper and dormant in practice, and no reachability test can tell the difference.
Two named sets each have a named caller.

Like ``procurement/validators.py`` the checks themselves are deliberately
**dependency-free**: standard library plus :class:`~decimal.Decimal`, no ORM, no
FastAPI, no session. The rule classes at the end of the file import the core
validation engine, and the core money renderer they quote amounts with, and
nothing else.

The clock is data, never ``date.today()``
-----------------------------------------
:data:`AS_OF_KEY` carries the date the checks treat as today. The service fills
it; a test passes it explicitly.

Two layers, one rule set pair
----------------------------
The check functions below are pure and are wrapped by rule classes in
``app.core.validation.rules`` (the ten that shipped with the module). The rule
classes further down this file are the module's own, registered into the same
two sets by :func:`register_rfq_validation_rules` from the package startup
hook. They cover what the module learned to model afterwards: the scope lines,
the standing of each quote and the comparison that ranks them.

Those later rules read the comparison's own verdict out of the payload rather
than recomputing it. Two implementations of "could this quote be ranked?" would
eventually disagree, and the one nobody would re-check is the report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

# The amount format the built-in rules already use: the decimals the currency
# genuinely has, thousands separators, and the code. Taken from the core rules
# rather than rewritten here, so two findings on one screen cannot disagree
# about what an amount looks like. Only the rule classes below use it; the
# check functions stay dependency-free. Importing it registers nothing.
from app.core.validation.rules import _fmt_money

logger = logging.getLogger(__name__)

#: Payload key carrying the date the checks should consider "now".
AS_OF_KEY = "as_of"

#: Fewer bids than this on an award is a single-source decision in all but name.
#: Three quotations is the common threshold in public and corporate procurement
#: policy alike, which is why it is the number worth flagging against.
MIN_COMPETITIVE_BIDS = 3


@dataclass(frozen=True)
class Finding:
    """One failed check on one element.

    :param element_ref: what the user should look at -- the RFQ number, or the
        bidder on a bid-level finding. Never ``None``: a finding the UI cannot
        anchor is a finding the user cannot act on.
    :param params: placeholders for the translated message, pre-formatted as
        strings so the message layer never formats dates or money itself.
    :param details: machine-readable context for the report payload.
    """

    element_ref: str
    params: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def parse_money(raw: Any) -> Decimal | None:
    """Parse a Decimal-string amount, or ``None`` when it is not a number."""
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_date(raw: Any) -> date | None:
    """Parse a date or the date part of an ISO datetime, or ``None``.

    ``submission_deadline`` and ``submitted_at`` are free-form string columns
    holding either a date or a full ISO timestamp, with or without a ``Z``
    suffix. Both shapes are accepted; a value that is neither is reported by
    :func:`check_deadline_parseable` rather than silently treated as absent.
    """
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_of(rfq: dict[str, Any]) -> date | None:
    """The date the checks treat as today, or ``None`` when the caller omitted it."""
    return parse_date(rfq.get(AS_OF_KEY))


def _ref(rfq: dict[str, Any]) -> str:
    return str(rfq.get("rfq_number") or rfq.get("title") or rfq.get("id") or "?")


def _bids(rfq: dict[str, Any]) -> list[dict[str, Any]]:
    bids = rfq.get("bids")
    return [b for b in bids if isinstance(b, dict)] if isinstance(bids, list) else []


def _recipients(rfq: dict[str, Any]) -> list[Any]:
    contacts = rfq.get("issued_to_contacts")
    return [c for c in contacts if str(c or "").strip()] if isinstance(contacts, list) else []


def _lines(rfq: dict[str, Any]) -> list[dict[str, Any]]:
    """The RFQ's scope lines, or an empty list when it has none."""
    lines = rfq.get("lines")
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def scope_line_label(line: dict[str, Any]) -> str:
    """A human label for a scope line: its number, its code, its description."""
    number = str(line.get("line_no") or "").strip()
    code = str(line.get("code") or "").strip()
    description = str(line.get("description") or "").strip()
    if len(description) > 40:
        description = description[:37] + "..."
    head = "-".join(part for part in (number, code) if part) or "?"
    return f"{head} ({description})" if description else head


def bid_label(index: int, bid: dict[str, Any]) -> str:
    """A human bid label: the 1-based row number plus the bidder reference."""
    bidder = str(bid.get("bidder_contact_id") or "").strip()
    if not bidder:
        return str(index + 1)
    if len(bidder) > 40:
        bidder = bidder[:37] + "..."
    return f"{index + 1} ({bidder})"


# ── Checks: what a vendor needs in order to bid ──────────────────────────────


def check_scope_described(rfq: dict[str, Any]) -> list[Finding]:
    """An RFQ must say what is being priced.

    A title alone is a subject line, not a scope. Vendors either decline, or
    price their own guess at the scope, which produces bids that cannot be
    compared with each other and a winner chosen on the narrowest assumption
    rather than the best offer.
    """
    if str(rfq.get("scope_of_work") or "").strip() or str(rfq.get("description") or "").strip():
        return []
    return [Finding(element_ref=_ref(rfq), details={"scope_of_work": None, "description": None})]


def check_deadline_present(rfq: dict[str, Any]) -> list[Finding]:
    """A published RFQ must state when bids close.

    Without a deadline there is no moment at which the field is complete, so the
    comparison happens whenever somebody decides to look and a bid that arrives
    afterwards has no principled answer.
    """
    if str(rfq.get("submission_deadline") or "").strip():
        return []
    return [Finding(element_ref=_ref(rfq), details={"submission_deadline": None})]


def check_deadline_parseable(rfq: dict[str, Any]) -> list[Finding]:
    """The deadline must be a date the system can actually read.

    ``submit_bid`` refuses every bid with HTTP 422 when it cannot parse this
    column. That refusal lands on the vendor, after the package went out, for a
    data-quality problem on our side. Publishing is when it costs nothing to
    fix. Reported only when a deadline exists: an absent one is
    :func:`check_deadline_present`'s finding, not this rule's.
    """
    raw = str(rfq.get("submission_deadline") or "").strip()
    if not raw or parse_date(raw) is not None:
        return []
    return [
        Finding(
            element_ref=_ref(rfq),
            params={"value": raw[:40]},
            details={"submission_deadline": raw},
        )
    ]


def check_deadline_in_future(rfq: dict[str, Any]) -> list[Finding]:
    """Bids must still be open at the moment the RFQ goes out.

    Publishing with a deadline already past means the package arrives closed:
    ``submit_bid`` rejects every response with HTTP 409, so the RFQ collects
    nothing and the buyer waits for bids that were refused on arrival.
    """
    deadline = parse_date(rfq.get("submission_deadline"))
    as_of = _as_of(rfq)
    if deadline is None or as_of is None or deadline >= as_of:
        return []
    return [
        Finding(
            element_ref=_ref(rfq),
            params={"deadline": deadline.isoformat(), "today": as_of.isoformat()},
            details={"submission_deadline": deadline.isoformat(), "as_of": as_of.isoformat()},
        )
    ]


def check_has_recipients(rfq: dict[str, Any]) -> list[Finding]:
    """A published RFQ must be addressed to somebody.

    Publishing to an empty recipient list changes the status and notifies no
    vendor, so the RFQ sits open and unanswered while it reads as issued on
    every dashboard.
    """
    if _recipients(rfq):
        return []
    return [Finding(element_ref=_ref(rfq), details={"issued_to_contacts": []})]


def check_currency_set(rfq: dict[str, Any]) -> list[Finding]:
    """The RFQ must state the currency bids are to be priced in.

    Bids are ranked by amount. Without a stated currency each vendor answers in
    its own and the ranking compares numbers that are not the same money.
    """
    if str(rfq.get("currency_code") or "").strip():
        return []
    return [Finding(element_ref=_ref(rfq), details={"currency_code": ""})]


# ── Checks: what the comparison between bids relies on ───────────────────────


def check_bid_currency_matches(rfq: dict[str, Any]) -> list[Finding]:
    """Every bid must be priced in the RFQ's currency.

    A bid in another currency sorts by its raw number against bids that are not
    the same money, so the cheapest row on screen may be the most expensive
    offer. The platform never converts silently, and an award taken from that
    table is an award taken from a comparison that did not happen.
    """
    currency = str(rfq.get("currency_code") or "").strip().upper()
    if not currency:
        # No RFQ currency to compare against: :func:`check_currency_set` owns
        # that finding, and reporting every bid against a blank would bury it.
        return []
    findings: list[Finding] = []
    for index, bid in enumerate(_bids(rfq)):
        bid_currency = str(bid.get("currency_code") or "").strip().upper()
        if bid_currency and bid_currency != currency:
            findings.append(
                Finding(
                    element_ref=bid_label(index, bid),
                    params={
                        "bid": bid_label(index, bid),
                        "bid_currency": bid_currency,
                        "rfq_currency": currency,
                    },
                    details={"bid_currency": bid_currency, "rfq_currency": currency},
                )
            )
    return findings


def check_bid_amounts_parseable(rfq: dict[str, Any]) -> list[Finding]:
    """Every bid amount must be a number.

    ``bid_amount`` is a free-form string column. A value that is not a number
    cannot be ranked, so it either drops out of the comparison or sorts
    somewhere arbitrary, and in both cases the award was decided over an
    incomplete field without anyone being told.
    """
    findings: list[Finding] = []
    for index, bid in enumerate(_bids(rfq)):
        amount = parse_money(bid.get("bid_amount"))
        if amount is None or amount <= 0:
            findings.append(
                Finding(
                    element_ref=bid_label(index, bid),
                    params={
                        "bid": bid_label(index, bid),
                        "value": str(bid.get("bid_amount") or "")[:40] or "?",
                    },
                    details={"bid_amount": bid.get("bid_amount")},
                )
            )
    return findings


def check_bids_still_valid(rfq: dict[str, Any]) -> list[Finding]:
    """A bid should still be inside its validity period when it is awarded.

    Every bid carries ``validity_days`` from its submission, and past that the
    price is an expression of interest rather than an offer. Awarding an expired
    bid invites a repricing before the contract is signed, which is exactly what
    the tender was meant to avoid. WARNING: a vendor will often honour a lapsed
    price, and that is a conversation rather than a refusal.
    """
    as_of = _as_of(rfq)
    if as_of is None:
        return []
    findings: list[Finding] = []
    for index, bid in enumerate(_bids(rfq)):
        submitted = parse_date(bid.get("submitted_at"))
        if submitted is None:
            continue
        try:
            validity = int(bid.get("validity_days") or 0)
        except (TypeError, ValueError):
            continue
        if validity <= 0:
            continue
        expires = submitted + timedelta(days=validity)
        if expires >= as_of:
            continue
        findings.append(
            Finding(
                element_ref=bid_label(index, bid),
                params={
                    "bid": bid_label(index, bid),
                    "expired": expires.isoformat(),
                    "today": as_of.isoformat(),
                },
                details={
                    "submitted_at": submitted.isoformat(),
                    "validity_days": validity,
                    "expires_on": expires.isoformat(),
                },
            )
        )
    return findings


def check_scope_lines_measurable(rfq: dict[str, Any]) -> list[Finding]:
    """Every scope line must carry a unit and a quantity somebody can price.

    A line with no unit, or with a quantity of zero, invites each supplier to
    assume its own and produces rates that cannot be compared with each other.
    Silent for an RFQ with no line breakdown at all: a lump-sum package is a
    legitimate way to ask, and :func:`check_scope_described` covers it.
    """
    findings: list[Finding] = []
    for line in _lines(rfq):
        quantity = parse_money(line.get("quantity"))
        unit = str(line.get("unit") or "").strip()
        problems = []
        if not unit:
            problems.append("unit")
        if quantity is None or quantity <= 0:
            problems.append("quantity")
        if problems:
            findings.append(
                Finding(
                    element_ref=scope_line_label(line),
                    params={"line": scope_line_label(line), "missing": ", ".join(problems)},
                    details={"unit": line.get("unit"), "quantity": line.get("quantity")},
                )
            )
    return findings


def check_scope_line_codes_unique(rfq: dict[str, Any]) -> list[Finding]:
    """Two scope lines must not share one reference code.

    Suppliers answer against the code they were given. Two lines carrying the
    same one means a returned price cannot be attached to a line with
    certainty, and the coverage figure that follows is a guess.
    """
    seen: dict[str, int] = {}
    for line in _lines(rfq):
        code = str(line.get("code") or "").strip().casefold()
        if code:
            seen[code] = seen.get(code, 0) + 1
    return [
        Finding(
            element_ref=code,
            params={"code": code, "count": str(count)},
            details={"code": code, "count": count},
        )
        for code, count in sorted(seen.items())
        if count > 1
    ]


def check_evaluation_basis_coherent(rfq: dict[str, Any]) -> list[Finding]:
    """The stated ranking method and its weight must agree with each other.

    A best-value RFQ with a technical weight of zero ranks on price while
    telling suppliers their technical answer counts, and a lowest-price RFQ
    with a weight set ignores the weight. Either way the suppliers were told
    something the award will not do.
    """
    method = str(rfq.get("evaluation_method") or "lowest_price").strip().lower()
    weight = parse_money(rfq.get("technical_weight")) or Decimal("0")
    if method == "best_value" and weight <= 0:
        return [
            Finding(
                element_ref=_ref(rfq),
                params={"method": method, "weight": str(weight)},
                details={"evaluation_method": method, "technical_weight": str(weight)},
            )
        ]
    if method != "best_value" and weight > 0:
        return [
            Finding(
                element_ref=_ref(rfq),
                params={"method": method, "weight": str(weight)},
                details={"evaluation_method": method, "technical_weight": str(weight)},
            )
        ]
    return []


def check_award_has_competition(rfq: dict[str, Any]) -> list[Finding]:
    """An award should rest on a field of bids, not on one.

    Awarding against fewer than :data:`MIN_COMPETITIVE_BIDS` responses is a
    single-source decision, which most procurement policies allow but require
    somebody to justify in writing. WARNING, so the justification is a
    deliberate act rather than something nobody noticed was needed.
    """
    count = len(_bids(rfq))
    if count >= MIN_COMPETITIVE_BIDS:
        return []
    return [
        Finding(
            element_ref=_ref(rfq),
            params={"count": str(count), "minimum": str(MIN_COMPETITIVE_BIDS)},
            details={"bid_count": count, "minimum": MIN_COMPETITIVE_BIDS},
        )
    ]


# ── Rule classes: the module's own, registered from the startup hook ─────────
#
# The ten rules that shipped with this module live in
# ``app.core.validation.rules`` and delegate to the check functions above. The
# rules below cover what came later - the scope lines, the standing of each
# quote and the comparison - and register into the same two sets, so a caller
# still asks for ``rfq_issue`` or ``rfq_award`` and gets everything that
# applies. They are registered by ``on_startup``; nothing else registers them,
# and a set that resolves to no rules is caught by the reachability test in the
# PostgreSQL lane.


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id, name, severity, category."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


def _payload(context: ValidationContext) -> dict[str, Any]:
    """The RFQ payload, or an empty dict when the caller passed something else."""
    return context.data if isinstance(context.data, dict) else {}


def _comparison(rfq: dict[str, Any]) -> dict[str, Any] | None:
    """The comparison the service attached, or ``None`` when it did not.

    A rule that reads the comparison stays silent without one rather than
    recomputing it: the caller that did not attach one is asking a different
    question, and answering it from a second implementation is how a report
    starts disagreeing with the ranking it describes.
    """
    comparison = rfq.get("comparison")
    return comparison if isinstance(comparison, dict) else None


def _comparison_quotes(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    """Every quote in the comparison, ranked and excluded alike."""
    rows: list[dict[str, Any]] = []
    for key in ("ranked", "excluded"):
        value = comparison.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    return rows


def _quote_ref(row: dict[str, Any]) -> str:
    """What the user should look at for a quote-level finding."""
    return str(row.get("bidder_contact_id") or row.get("bid_id") or "?")


def _basis_currency(comparison: dict[str, Any]) -> str:
    """The currency the comparison normalised every quote into, or empty.

    ``basis_currency`` is nullable, and the sentences below used to write the
    word ``None`` straight into the message when it was. Empty is rendered as
    no code at all rather than as a guess.
    """
    return str(comparison.get("basis_currency") or "").strip()


def _quoted(raw: Any, currency: str) -> str:
    """Render a comparison amount for a sentence, tolerating what it holds.

    The comparison serialises money as a Decimal *string*, and leaves it
    ``None`` where a quote states none. The renderer is therefore reached
    through a parse: handing a string to a format spec raises, and a rule that
    raises turns the warning it was trying to show into a failed request.
    """
    amount = parse_money(raw)
    return "an unstated amount" if amount is None else _fmt_money(amount, currency)


class RFQScopeLinesMeasurable(ValidationRule):
    """Every scope line must carry a unit and a quantity somebody can price."""

    rule_id = "rfq.scope_lines_measurable"
    name = "RFQ Scope Lines Measurable"
    standard = "rfq"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags a scope line with no unit or a non-positive quantity, which each supplier would guess at."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        findings = check_scope_lines_measurable(_payload(context))
        if not findings:
            return [_result(self, True, "Every scope line carries a unit and a quantity.")]
        return [
            _result(
                self,
                False,
                (
                    f"Scope line {finding.params['line']} has no {finding.params['missing']}, "
                    "so each supplier prices its own assumption."
                ),
                element_ref=finding.element_ref,
                suggestion="Give the line a unit of measure and a positive quantity before the RFQ goes out.",
                details=dict(finding.details),
            )
            for finding in findings
        ]


class RFQScopeLineCodesUnique(ValidationRule):
    """Two scope lines must not share one reference code."""

    rule_id = "rfq.scope_line_codes_unique"
    name = "RFQ Scope Line Codes Unique"
    standard = "rfq"
    severity = Severity.WARNING
    category = RuleCategory.STRUCTURE
    description = "Flags a reference code used on more than one scope line, which makes returned prices ambiguous."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        findings = check_scope_line_codes_unique(_payload(context))
        if not findings:
            return [_result(self, True, "Scope line reference codes are unique.")]
        return [
            _result(
                self,
                False,
                (
                    f"Reference code '{finding.params['code']}' is used on {finding.params['count']} scope lines, "
                    "so a returned price cannot be attached to one of them with certainty."
                ),
                element_ref=finding.element_ref,
                suggestion="Give each scope line its own reference code.",
                details=dict(finding.details),
            )
            for finding in findings
        ]


class RFQEvaluationBasisCoherent(ValidationRule):
    """The stated ranking method and its technical weight must agree."""

    rule_id = "rfq.evaluation_basis_coherent"
    name = "RFQ Evaluation Basis Coherent"
    standard = "rfq"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Flags a ranking method whose technical weight contradicts it, so suppliers were told the wrong basis."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        findings = check_evaluation_basis_coherent(_payload(context))
        if not findings:
            return [_result(self, True, "The ranking method and its technical weight agree.")]
        return [
            _result(
                self,
                False,
                (
                    f"This RFQ is evaluated as '{finding.params['method']}' with a technical weight of "
                    f"{finding.params['weight']}, so the basis suppliers were given is not the one the award uses."
                ),
                element_ref=finding.element_ref,
                suggestion="Set a technical weight above zero for best value, or leave it at zero for lowest price.",
                details=dict(finding.details),
            )
            for finding in findings
        ]


class RFQQuoteComparable(ValidationRule):
    """Every quote must be one the comparison could put on the RFQ's basis."""

    rule_id = "rfq.quote_comparable"
    name = "RFQ Quote Comparable"
    standard = "rfq"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a quote the comparison could not restate on the RFQ's basis, so it never entered the ranking."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        comparison = _comparison(_payload(context))
        if comparison is None:
            return []
        excluded = [row for row in _comparison_quotes(comparison) if not row.get("comparable")]
        if not excluded:
            return [_result(self, True, "Every quote could be restated on the RFQ's basis.")]
        return [
            _result(
                self,
                False,
                (
                    f"Quote from {_quote_ref(row)} is not in the ranking: "
                    f"{', '.join(str(reason) for reason in row.get('reasons') or []) or 'no reason recorded'}."
                ),
                element_ref=_quote_ref(row),
                suggestion=(
                    "Record the exchange rate, admit the late quote, price the missing scope or allow partial "
                    "quotes on this RFQ, and the quote can then be compared with the others."
                ),
                details={"bid_id": row.get("bid_id"), "reasons": row.get("reasons") or []},
            )
            for row in excluded
        ]


class RFQQuoteCoversScope(ValidationRule):
    """A quote should price the whole scope it was asked to price."""

    rule_id = "rfq.quote_covers_scope"
    name = "RFQ Quote Covers Scope"
    standard = "rfq"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a quote that priced only part of the scope, which reads cheaper than a quote for all of it."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        comparison = _comparison(_payload(context))
        if comparison is None:
            return []
        partial = [
            row
            for row in _comparison_quotes(comparison)
            if int(row.get("lines_required") or 0) > 0
            and int(row.get("lines_covered") or 0) < int(row.get("lines_required") or 0)
        ]
        if not partial:
            return [_result(self, True, "Every quote prices the whole scope.")]
        return [
            _result(
                self,
                False,
                (
                    f"Quote from {_quote_ref(row)} prices {row.get('lines_covered')} of "
                    f"{row.get('lines_required')} scope lines, so its total is not for the same work as the others."
                ),
                element_ref=_quote_ref(row),
                suggestion=(
                    "Ask the supplier to price the missing lines, or record a buyer allowance for them so the "
                    "comparison adds the gap back."
                ),
                details={
                    "bid_id": row.get("bid_id"),
                    "lines_covered": row.get("lines_covered"),
                    "lines_required": row.get("lines_required"),
                    "uncovered_lines": row.get("uncovered_lines") or [],
                    "excluded_lines": row.get("excluded_lines") or [],
                },
            )
            for row in partial
        ]


class RFQQuoteLinesMatchTotal(ValidationRule):
    """A quote's priced lines must add up to the amount it is offering."""

    rule_id = "rfq.quote_lines_match_total"
    name = "RFQ Quote Lines Match Total"
    standard = "rfq"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a quote whose priced lines do not sum to its headline amount, so one of the two is wrong."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        comparison = _comparison(_payload(context))
        if comparison is None:
            return []
        mismatched = [
            row for row in _comparison_quotes(comparison) if "lines_disagree_with_total" in (row.get("notes") or [])
        ]
        if not mismatched:
            return [_result(self, True, "Every quote's lines add up to the amount offered.")]
        currency = _basis_currency(comparison)
        return [
            _result(
                self,
                False,
                (
                    f"Quote from {_quote_ref(row)} offers {_quoted(row.get('headline_amount'), currency)} "
                    f"but its lines add up to {_quoted(row.get('line_total'), currency)}, "
                    "so the ranking and the detail behind it disagree."
                ),
                element_ref=_quote_ref(row),
                suggestion="Ask the supplier which number stands, and correct the other before ranking the field.",
                details={
                    "bid_id": row.get("bid_id"),
                    "headline_amount": row.get("headline_amount"),
                    "line_total": row.get("line_total"),
                },
            )
            for row in mismatched
        ]


class RFQLateQuoteInField(ValidationRule):
    """A quote that arrived after the deadline must be visible as such."""

    rule_id = "rfq.late_quote_in_field"
    name = "RFQ Late Quote In Field"
    standard = "rfq"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags a quote received after the deadline, whether or not the buyer admitted it into the ranking."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        comparison = _comparison(_payload(context))
        if comparison is None:
            return []
        late = [row for row in _comparison_quotes(comparison) if bool(row.get("is_late"))]
        if not late:
            return [_result(self, True, "Every quote arrived before the deadline.")]
        return [
            _result(
                self,
                False,
                (
                    f"Quote from {_quote_ref(row)} arrived after the deadline and "
                    + ("was admitted into the ranking." if row.get("admitted") else "is not in the ranking.")
                ),
                element_ref=_quote_ref(row),
                suggestion=(
                    "A late quote admitted after the other prices are known is contestable; make sure the reason "
                    "for admitting it is on the record."
                ),
                details={"bid_id": row.get("bid_id"), "admitted": bool(row.get("admitted"))},
            )
            for row in late
        ]


class RFQAwardFollowsRanking(ValidationRule):
    """An award that passes over the top-ranked quote must be a deliberate act."""

    rule_id = "rfq.award_follows_ranking"
    name = "RFQ Award Follows Ranking"
    standard = "rfq"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags an award taken from a quote the comparison did not rank first."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        comparison = _comparison(payload)
        candidate = str(payload.get("candidate_bid_id") or "").strip()
        if comparison is None or not candidate:
            return []
        recommended = str(comparison.get("recommended_bid_id") or "").strip()
        if not recommended or recommended == candidate:
            return [_result(self, True, "The award goes to the quote the comparison ranked first.")]
        rows = {str(row.get("bid_id")): row for row in _comparison_quotes(comparison)}
        chosen = rows.get(candidate, {})
        best = rows.get(recommended, {})
        currency = _basis_currency(comparison)
        return [
            _result(
                self,
                False,
                (
                    f"The award goes to {_quote_ref(chosen)} at "
                    f"{_quoted(chosen.get('normalised_amount'), currency)}, "
                    f"while the comparison ranks {_quote_ref(best)} first at "
                    f"{_quoted(best.get('normalised_amount'), currency)}."
                ),
                element_ref=_quote_ref(chosen),
                suggestion="Record why this quote was preferred; the award keeps the ranked table it departed from.",
                details={
                    "awarded_bid_id": candidate,
                    "recommended_bid_id": recommended,
                    "awarded_amount": chosen.get("normalised_amount"),
                    "recommended_amount": best.get("normalised_amount"),
                },
            )
        ]


class RFQExclusionsPriced(ValidationRule):
    """An item a supplier excluded has to carry the amount it would cost."""

    rule_id = "rfq.exclusions_priced"
    name = "RFQ Exclusions Priced"
    standard = "rfq"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags an exclusion recorded with no amount, which the comparison cannot add back to the quote."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for index, bid in enumerate(_bids(_payload(context))):
            adjustments = bid.get("adjustments")
            rows = [row for row in adjustments if isinstance(row, dict)] if isinstance(adjustments, list) else []
            unpriced = [
                row
                for row in rows
                if not bool(row.get("included_in_bid")) and (parse_money(row.get("amount")) or Decimal("0")) == 0
            ]
            if not unpriced:
                continue
            kinds = ", ".join(str(row.get("kind") or "other") for row in unpriced)
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"Quote {bid_label(index, bid)} excludes {kinds} without an amount, so the comparison "
                        "cannot add the gap back and this quote looks cheaper than it is."
                    ),
                    element_ref=bid_label(index, bid),
                    suggestion="Record what the excluded item costs, as a buyer allowance if the supplier will not.",
                    details={"kinds": [row.get("kind") for row in unpriced]},
                )
            )
        if not results:
            return [_result(self, True, "Every recorded exclusion carries an amount.")]
        return results


#: Rules this module registers itself, beyond the ten in the core rule file.
_RFQ_ISSUE_RULES: tuple[ValidationRule, ...] = (
    RFQScopeLinesMeasurable(),
    RFQScopeLineCodesUnique(),
)

_RFQ_AWARD_RULES: tuple[ValidationRule, ...] = (
    RFQQuoteComparable(),
    RFQQuoteCoversScope(),
    RFQQuoteLinesMatchTotal(),
    RFQLateQuoteInField(),
    RFQAwardFollowsRanking(),
    RFQExclusionsPriced(),
)

#: Registered into both sets: the basis suppliers were given is worth checking
#: when the package goes out and again when the award is taken from it.
_RFQ_BOTH_RULES: tuple[ValidationRule, ...] = (RFQEvaluationBasisCoherent(),)


def register_rfq_validation_rules() -> None:
    """Register this module's rules with the core rule registry.

    Idempotent: the registry keys rules by id, so a re-import or a hot reload
    re-registers cleanly. Called from the package ``on_startup`` hook, and
    directly by tests, which do not run startup hooks.
    """
    from app.modules.rfq_bidding.service import RFQ_AWARD_RULE_SET, RFQ_ISSUE_RULE_SET

    for rule in _RFQ_ISSUE_RULES:
        rule_registry.register(rule, [RFQ_ISSUE_RULE_SET])
    for rule in _RFQ_AWARD_RULES:
        rule_registry.register(rule, [RFQ_AWARD_RULE_SET])
    for rule in _RFQ_BOTH_RULES:
        rule_registry.register(rule, [RFQ_ISSUE_RULE_SET, RFQ_AWARD_RULE_SET])
    logger.debug(
        "Registered %d rfq_bidding validation rules",
        len(_RFQ_ISSUE_RULES) + len(_RFQ_AWARD_RULES) + len(_RFQ_BOTH_RULES),
    )
