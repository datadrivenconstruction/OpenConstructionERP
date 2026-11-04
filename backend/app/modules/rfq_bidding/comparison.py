# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Put quotes on one basis before ranking them.

An RFQ goes out to several suppliers and the answers come back on different
terms: another currency, another unit of measure, delivery included in one
price and excluded from the next, one supplier pricing eight of the ten scope
lines. Sorting those headline numbers produces an order, and the order means
nothing. This module turns a set of quotes into a comparison whose ranking is
defensible, and which says out loud what it could not compare.

The rules it follows, in order:

1. **Standing first.** A withdrawn or disqualified quote never ranks. A quote
   that arrived after the deadline ranks only once the buyer has admitted it on
   the record; until then it stays in the table and out of the order.
2. **One currency, at a rate that was written down.** Nothing is converted on a
   guess. A quote in another currency with no rate recorded against it is
   reported as not comparable rather than ranked at its face value.
3. **Add back what is missing, and say where the number came from.** An item
   the supplier excluded is added to their comparable total at the amount
   recorded for it. Scope nobody priced is a gap. When the RFQ requires full
   scope the quote is reported as covering part of it and stays out of the
   order. When the RFQ allows partial quotes the gap is plugged with the
   shared rule of :mod:`app.modules.bid_management.plugs` (median of the other
   quotes, the estimate rate, a single other quote), so a quote that left line
   7 out no longer looks cheapest. Every plug carries its source; a gap with no
   source at all is reported loudly (the plug is zero and the quote is flagged). A line priced at zero on
   purpose is covered and is not plugged. Plugs are computed on the fly from the
   quotes, never stored, and the raw total is always reported beside the plugged
   one.
4. **Only then rank**, on the normalised amount, or on a weighted blend of
   amount and technical score when the RFQ was issued that way.

Everything here is pure: dictionaries in, dataclasses out, :class:`Decimal`
throughout, no ORM, no session, no float. The clock arrives as data (``as_of``)
exactly as it does in :mod:`app.modules.rfq_bidding.validators`, so a test can
pin it and a comparison can be recomputed for the date it was made on.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any

from app.modules.bid_management.plugs import GAP_STATUSES, compute_plugs
from app.modules.rfq_bidding.validators import parse_date, parse_money

#: Money is reported to two decimals; the arithmetic itself is exact.
MONEY_QUANT = Decimal("0.01")

#: Ratios and scores are reported to four decimals.
RATIO_QUANT = Decimal("0.0001")

#: A quote's priced lines may differ from its headline amount by this much
#: before the difference is worth telling somebody about. One cent per line
#: rounds up quickly, so the tolerance is a small absolute amount rather than
#: zero.
LINE_TOTAL_TOLERANCE = Decimal("0.05")

# ── Reasons a quote is kept out of the ranking ───────────────────────────────

REASON_WITHDRAWN = "withdrawn"
REASON_DISQUALIFIED = "disqualified"
REASON_LATE_NOT_ADMITTED = "late_not_admitted"
REASON_AMOUNT_UNREADABLE = "amount_unreadable"
REASON_CURRENCY_NOT_CONVERTED = "currency_not_converted"
REASON_ADJUSTMENT_UNREADABLE = "adjustment_unreadable"
REASON_ADJUSTMENT_CURRENCY = "adjustment_currency_not_converted"
REASON_UNIT_NOT_CONVERTIBLE = "unit_not_convertible"
REASON_SCOPE_NOT_COVERED = "scope_not_covered"
REASON_TOTAL_NOT_POSITIVE = "normalised_total_not_positive"
REASON_TECHNICAL_SCORE_MISSING = "technical_score_missing"
REASON_LUMP_SUM_NEEDS_CLARIFICATION = "lump_sum_exceeds_lines_needs_clarification"
REASON_SCOPE_UNCONFIRMED = "lump_sum_scope_unconfirmed"

# ── Things worth saying about a quote that still ranks ───────────────────────

NOTE_LATE_ADMITTED = "late_admitted"
NOTE_PARTIAL_SCOPE = "partial_scope"
NOTE_EXTRA_LINES = "extra_lines_priced"
NOTE_LINES_DISAGREE = "lines_disagree_with_total"
NOTE_VALIDITY_EXPIRED = "validity_expired"
NOTE_ADJUSTED = "adjusted_for_exclusions"
NOTE_CONVERTED = "converted_to_basis_currency"
NOTE_PLUGGED = "ranked_on_plugged_total"
NOTE_GAP_NOT_PLUGGABLE = "gap_not_pluggable"

#: Plug source reported when the median rests on only two other quotes: that is
#: their mean, a thin market, and the buyer should read it as such.
SOURCE_MEDIAN_OF_2 = "median_of_2"

#: Ranking methods, mirroring ``RFQ.evaluation_method``.
METHOD_LOWEST_PRICE = "lowest_price"
METHOD_BEST_VALUE = "best_value"


def _money(value: Decimal) -> str:
    """Render an amount for the report: two decimals, never an exponent."""
    return f"{value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP):f}"


def _ratio(value: Decimal) -> str:
    """Render a ratio or score for the report, four decimals."""
    return f"{value.quantize(RATIO_QUANT, rounding=ROUND_HALF_UP):f}"


def _unit(raw: Any) -> str:
    """Normalise a unit of measure for comparison: trimmed, case-folded."""
    return str(raw or "").strip().casefold()


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def _rows(container: Any, key: str) -> list[dict[str, Any]]:
    """Read a list of dict rows off a payload, tolerating anything else."""
    rows = container.get(key) if isinstance(container, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def line_ref(line: dict[str, Any]) -> str:
    """A human reference for a scope line: its number, code and description."""
    number = _text(line.get("line_no"))
    code = _text(line.get("code"))
    description = _text(line.get("description"))
    if len(description) > 40:
        description = description[:37] + "..."
    head = "-".join(part for part in (number, code) if part) or "?"
    return f"{head} ({description})" if description else head


@dataclass(frozen=True)
class QuoteComparison:
    """One quote, restated on the RFQ's basis.

    ``normalised_amount`` is the number the ranking uses: the headline amount
    converted into the RFQ currency and moved by the adjustments the quote did
    not already carry. It is ``None`` whenever the quote could not be brought
    onto the basis at all, and ``reasons`` then says why in terms a buyer can
    act on.
    """

    bid_id: str
    bidder_contact_id: str
    status: str
    is_late: bool
    admitted: bool
    currency_code: str
    headline_amount: Decimal | None
    exchange_rate: Decimal | None
    converted_amount: Decimal | None
    adjustments_applied: Decimal
    adjustments_included: int
    normalised_amount: Decimal | None
    lines_required: int
    lines_covered: int
    coverage: Decimal
    uncovered_lines: tuple[str, ...]
    excluded_lines: tuple[str, ...]
    extra_lines: int
    line_total: Decimal | None
    technical_score: Decimal | None
    price_score: Decimal | None
    total_score: Decimal | None
    comparable: bool
    reasons: tuple[str, ...]
    notes: tuple[str, ...]
    rank: int | None = None
    raw_total: Decimal | None = None
    plug_total: Decimal = Decimal("0")
    plugged_total: Decimal | None = None
    plugs_applied: bool = False
    plug_sources: tuple[dict[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Flatten to JSON-safe values for the API and the award record."""
        return {
            "bid_id": self.bid_id,
            "bidder_contact_id": self.bidder_contact_id,
            "status": self.status,
            "is_late": self.is_late,
            "admitted": self.admitted,
            "currency_code": self.currency_code,
            "headline_amount": None if self.headline_amount is None else _money(self.headline_amount),
            "exchange_rate": None if self.exchange_rate is None else f"{self.exchange_rate:f}",
            "converted_amount": None if self.converted_amount is None else _money(self.converted_amount),
            "adjustments_applied": _money(self.adjustments_applied),
            "adjustments_included": self.adjustments_included,
            "normalised_amount": None if self.normalised_amount is None else _money(self.normalised_amount),
            "lines_required": self.lines_required,
            "lines_covered": self.lines_covered,
            "coverage": _ratio(self.coverage),
            "uncovered_lines": list(self.uncovered_lines),
            "excluded_lines": list(self.excluded_lines),
            "extra_lines": self.extra_lines,
            "line_total": None if self.line_total is None else _money(self.line_total),
            "technical_score": None if self.technical_score is None else _ratio(self.technical_score),
            "price_score": None if self.price_score is None else _ratio(self.price_score),
            "total_score": None if self.total_score is None else _ratio(self.total_score),
            "comparable": self.comparable,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "rank": self.rank,
            "raw_total": None if self.raw_total is None else _money(self.raw_total),
            "plug_total": _money(self.plug_total),
            "plugged_total": None if self.plugged_total is None else _money(self.plugged_total),
            "plugs_applied": self.plugs_applied,
            "plug_sources": [dict(row) for row in self.plug_sources],
        }


@dataclass(frozen=True)
class ComparisonResult:
    """The ranked field of quotes, plus the ones that could not be ranked."""

    basis_currency: str
    method: str
    technical_weight: Decimal
    require_full_scope: bool
    as_of: str | None
    lines_required: int
    ranked: tuple[QuoteComparison, ...]
    excluded: tuple[QuoteComparison, ...]
    recommended_bid_id: str | None

    @property
    def quotes(self) -> tuple[QuoteComparison, ...]:
        """Every quote, ranked ones first, in the order a table shows them."""
        return self.ranked + self.excluded

    def get(self, bid_id: str) -> QuoteComparison | None:
        """The comparison row for one quote, or ``None`` when it has none."""
        for quote in self.quotes:
            if quote.bid_id == bid_id:
                return quote
        return None

    def as_dict(self) -> dict[str, Any]:
        """Flatten to JSON-safe values for the API and the award record."""
        return {
            "basis_currency": self.basis_currency,
            "method": self.method,
            "technical_weight": _ratio(self.technical_weight),
            "require_full_scope": self.require_full_scope,
            "as_of": self.as_of,
            "lines_required": self.lines_required,
            "recommended_bid_id": self.recommended_bid_id,
            "ranked": [quote.as_dict() for quote in self.ranked],
            "excluded": [quote.as_dict() for quote in self.excluded],
        }


def _standing_reasons(bid: dict[str, Any]) -> tuple[list[str], list[str], bool]:
    """Whether the quote is allowed to rank at all, before any arithmetic."""
    reasons: list[str] = []
    notes: list[str] = []
    status = _text(bid.get("status")) or "received"
    admitted = bool(_text(bid.get("admitted_at")))
    if status == "withdrawn":
        reasons.append(REASON_WITHDRAWN)
    if status == "disqualified":
        reasons.append(REASON_DISQUALIFIED)
    if bool(bid.get("is_late")) or status == "late":
        if admitted:
            notes.append(NOTE_LATE_ADMITTED)
        else:
            reasons.append(REASON_LATE_NOT_ADMITTED)
    return reasons, notes, admitted


def _convert(amount: Decimal, rate: Decimal | None) -> Decimal | None:
    """Apply a recorded rate; ``None`` rate means the amount cannot be moved."""
    return None if rate is None else amount * rate


def _quote_rate(bid: dict[str, Any], basis_currency: str) -> tuple[str, Decimal | None]:
    """The quote's currency and the rate that takes it to the basis currency."""
    currency = _text(bid.get("currency_code")).upper()
    if not currency or currency == basis_currency:
        return currency or basis_currency, Decimal("1")
    rate = parse_money(bid.get("exchange_rate"))
    if rate is None or rate <= 0:
        return currency, None
    return currency, rate


def _apply_adjustments(
    bid: dict[str, Any],
    *,
    basis_currency: str,
    quote_currency: str,
    quote_rate: Decimal | None,
) -> tuple[Decimal, int, list[str], list[str]]:
    """Sum the adjustments the quote does not already carry.

    An item the supplier marked as included needs no arithmetic: the headline
    already holds it, and it is counted only so the report can show what each
    price covers. Everything else is added, signed, so a discount reduces the
    comparable total and an excluded delivery charge raises it.
    """
    total = Decimal("0")
    included = 0
    reasons: list[str] = []
    notes: list[str] = []
    for row in _rows(bid, "adjustments"):
        if bool(row.get("included_in_bid")):
            included += 1
            continue
        amount = parse_money(row.get("amount"))
        if amount is None:
            reasons.append(REASON_ADJUSTMENT_UNREADABLE)
            continue
        currency = _text(row.get("currency_code")).upper() or quote_currency
        if currency == basis_currency:
            converted: Decimal | None = amount
        elif currency == quote_currency:
            converted = _convert(amount, quote_rate)
            if converted is None:
                reasons.append(REASON_CURRENCY_NOT_CONVERTED)
                continue
        else:
            reasons.append(REASON_ADJUSTMENT_CURRENCY)
            continue
        total += converted
        if converted != 0:
            notes.append(NOTE_ADJUSTED)
    return total, included, reasons, notes


def _cover_scope(
    bid: dict[str, Any],
    required: list[dict[str, Any]],
) -> tuple[int, list[str], list[str], int, Decimal | None, list[str]]:
    """Measure what the quote priced against what the RFQ asked for.

    Returns the covered count, the references of the lines nobody priced, the
    references the supplier explicitly excluded, how many extra lines they
    priced, the sum of their priced lines, and any unit that could not be
    reconciled with the RFQ's own.
    """
    by_id = {_text(line.get("id")): line for line in required if _text(line.get("id"))}
    covered: set[str] = set()
    excluded_refs: list[str] = []
    reasons: list[str] = []
    extra = 0
    line_total = Decimal("0")
    seen_line = False
    for row in _rows(bid, "lines"):
        rfq_line_id = _text(row.get("rfq_line_id"))
        target = by_id.get(rfq_line_id)
        amount = parse_money(row.get("amount"))
        if amount is not None and not bool(row.get("is_excluded")):
            line_total += amount
            seen_line = True
        if target is None:
            if not rfq_line_id:
                extra += 1
            continue
        if bool(row.get("is_excluded")):
            excluded_refs.append(line_ref(target))
            continue
        quoted_unit = _unit(row.get("unit"))
        wanted_unit = _unit(target.get("unit"))
        if quoted_unit and wanted_unit and quoted_unit != wanted_unit:
            factor = parse_money(row.get("unit_conversion_factor"))
            if factor is None or factor <= 0:
                reasons.append(REASON_UNIT_NOT_CONVERTIBLE)
        covered.add(rfq_line_id)
    uncovered = [line_ref(line) for key, line in by_id.items() if key not in covered]
    return (
        len(covered),
        uncovered,
        excluded_refs,
        extra,
        line_total if seen_line else None,
        reasons,
    )


def _plan_plugs(
    bids: list[dict[str, Any]],
    required: list[dict[str, Any]],
    basis_currency: str,
) -> dict[str, list[dict[str, str]]]:
    """Price every gap of every standing quote with the shared plug rule.

    Only quotes that are allowed to rank and can be moved to the basis currency
    take part, as a market and as a receiver: a withdrawn or unconverted quote
    must not set the price another quote is plugged at. Prices are restated in
    the basis currency first, so a plug is in the currency the ranking uses.
    """
    ids = {_text(line.get("id")) for line in required if _text(line.get("id"))}
    lines = [
        SimpleNamespace(id=_text(line.get("id")), quantity=parse_money(line.get("quantity")) or Decimal("0"))
        for line in required
        if _text(line.get("id"))
    ]
    # An estimate rate carries no conversion: one stated in another currency is
    # refused rather than read as basis money. No stated currency means basis.
    rates = {
        _text(line.get("id")): rate
        for line in required
        if _text(line.get("id"))
        and _text(line.get("estimate_currency")).upper() in ("", basis_currency)
        and (rate := parse_money(line.get("estimate_rate"))) is not None
        and rate > 0
    }
    priced: dict[str, dict[str, tuple[Decimal, str]]] = {}
    zero_on_purpose: dict[str, set[str]] = {}
    for bid in bids:
        bid_id = _text(bid.get("id"))
        # A headline-only quote has no line detail to plug against: adding a
        # plug for every line to its lump sum would count the whole scope twice.
        if _standing_reasons(bid)[0] or not _rows(bid, "lines"):
            continue
        _currency, rate = _quote_rate(bid, basis_currency)
        if rate is None:
            continue
        rows: dict[str, tuple[Decimal, str]] = {}
        for row in _rows(bid, "lines"):
            line_id = _text(row.get("rfq_line_id"))
            if line_id not in ids:
                continue
            if bool(row.get("is_excluded")):
                rows.setdefault(line_id, (Decimal("0"), "excluded"))
                continue
            amount = parse_money(row.get("amount"))
            if amount is None:
                continue
            if amount <= 0:  # a free line or a credit is an answer, not a gap
                zero_on_purpose.setdefault(bid_id, set()).add(line_id)
            previous = rows.get(line_id)
            base = previous[0] if previous and previous[1] not in GAP_STATUSES else Decimal("0")
            rows[line_id] = (base + amount * rate, "included")
        priced[bid_id] = rows
    if not priced:
        return {}
    plugs = compute_plugs(lines, priced, estimate_rates=rates)
    by_line = {_text(line.get("id")): line for line in required}
    out: dict[str, list[dict[str, str]]] = {}
    for bid_id, found in plugs.items():
        rows_out: list[dict[str, str]] = []
        for plug in found:
            if plug.line_item_id in zero_on_purpose.get(bid_id, ()):
                continue
            source = plug.source
            if source == "median":
                others = sum(
                    1
                    for other, other_rows in priced.items()
                    if other != bid_id
                    and plug.line_item_id in other_rows
                    and other_rows[plug.line_item_id][1] not in GAP_STATUSES
                    and other_rows[plug.line_item_id][0] > 0
                )
                if others == 2:
                    source = SOURCE_MEDIAN_OF_2
            rows_out.append(
                {
                    "line_id": plug.line_item_id,
                    "line": line_ref(by_line[plug.line_item_id]),
                    "amount": _money(plug.amount),
                    "source": source,
                    "reason": plug.reason,
                }
            )
        out[bid_id] = rows_out
    return out


def _validity_note(bid: dict[str, Any], as_of: Any) -> list[str]:
    """Flag a quote whose own validity period ran out before ``as_of``."""
    today = parse_date(as_of)
    submitted = parse_date(bid.get("submitted_at"))
    if today is None or submitted is None:
        return []
    try:
        days = int(bid.get("validity_days") or 0)
    except (TypeError, ValueError):
        return []
    if days <= 0:
        return []
    return [NOTE_VALIDITY_EXPIRED] if submitted + timedelta(days=days) < today else []


def _compare_one(
    bid: dict[str, Any],
    *,
    basis_currency: str,
    required: list[dict[str, Any]],
    require_full_scope: bool,
    as_of: Any,
    plugs: list[dict[str, str]] | None = None,
) -> QuoteComparison:
    """Restate one quote on the RFQ's basis, collecting every objection."""
    reasons, notes, admitted = _standing_reasons(bid)

    headline = parse_money(bid.get("bid_amount"))
    if headline is None or headline <= 0:
        reasons.append(REASON_AMOUNT_UNREADABLE)
        headline = None

    quote_currency, rate = _quote_rate(bid, basis_currency)
    if rate is None:
        reasons.append(REASON_CURRENCY_NOT_CONVERTED)
    elif rate != 1:
        notes.append(NOTE_CONVERTED)

    converted = None if headline is None else _convert(headline, rate)

    adjustments, included, adj_reasons, adj_notes = _apply_adjustments(
        bid,
        basis_currency=basis_currency,
        quote_currency=quote_currency,
        quote_rate=rate,
    )
    reasons.extend(adj_reasons)
    notes.extend(adj_notes)

    covered, uncovered, excluded_refs, extra, line_total, unit_reasons = _cover_scope(bid, required)
    reasons.extend(unit_reasons)
    if uncovered or excluded_refs:
        notes.append(NOTE_PARTIAL_SCOPE)
        if require_full_scope:
            reasons.append(REASON_SCOPE_NOT_COVERED)
    if extra:
        notes.append(NOTE_EXTRA_LINES)
    if line_total is not None and headline is not None and abs(line_total - headline) > LINE_TOTAL_TOLERANCE:
        notes.append(NOTE_LINES_DISAGREE)
    notes.extend(_validity_note(bid, as_of))

    plugs = plugs or []
    apply_plugs = not require_full_scope
    if apply_plugs and plugs and line_total is not None and headline is not None:
        if headline - line_total > LINE_TOTAL_TOLERANCE:
            # The lump sum may already cover the unlisted items: a plug on top
            # would count them twice, so the estimator is asked instead.
            reasons.append(REASON_LUMP_SUM_NEEDS_CLARIFICATION)
            plugs = []
    if apply_plugs and line_total is None and uncovered and not bool(bid.get("scope_confirmed")):
        reasons.append(REASON_SCOPE_UNCONFIRMED)
    plug_total = sum((Decimal(row["amount"]) for row in plugs), Decimal("0"))
    if apply_plugs and any(row["source"] == "none" for row in plugs):
        notes.append(NOTE_GAP_NOT_PLUGGABLE)
    if apply_plugs and plugs:
        notes.append(NOTE_PLUGGED)

    raw_total = None if converted is None else converted + adjustments
    plugged_total = None if raw_total is None else raw_total + plug_total
    normalised = plugged_total if apply_plugs else raw_total
    if normalised is not None and normalised <= 0:
        reasons.append(REASON_TOTAL_NOT_POSITIVE)

    coverage = Decimal("1") if not required else Decimal(covered) / Decimal(len(required))
    unique_reasons = tuple(dict.fromkeys(reasons))
    return QuoteComparison(
        bid_id=_text(bid.get("id")),
        bidder_contact_id=_text(bid.get("bidder_contact_id")),
        status=_text(bid.get("status")) or "received",
        is_late=bool(bid.get("is_late")),
        admitted=admitted,
        currency_code=quote_currency,
        headline_amount=headline,
        exchange_rate=rate,
        converted_amount=converted,
        adjustments_applied=adjustments,
        adjustments_included=included,
        normalised_amount=None if unique_reasons else normalised,
        lines_required=len(required),
        lines_covered=covered,
        coverage=coverage,
        uncovered_lines=tuple(uncovered),
        excluded_lines=tuple(excluded_refs),
        extra_lines=extra,
        line_total=line_total,
        technical_score=parse_money(bid.get("technical_score")),
        price_score=None,
        total_score=None,
        comparable=not unique_reasons,
        reasons=unique_reasons,
        notes=tuple(dict.fromkeys(notes)),
        raw_total=raw_total,
        plug_total=plug_total,
        plugged_total=plugged_total,
        plugs_applied=apply_plugs and bool(plugs),
        plug_sources=tuple(plugs),
    )


def _weight(rfq: dict[str, Any]) -> Decimal:
    """The technical weight, clamped to 0-100; anything unreadable is zero."""
    weight = parse_money(rfq.get("technical_weight"))
    if weight is None or weight < 0:
        return Decimal("0")
    return min(weight, Decimal("100"))


def _score(quotes: list[QuoteComparison], weight: Decimal) -> list[QuoteComparison]:
    """Blend price and technical score into one number per quote.

    The price score is the cheapest comparable amount as a percentage of this
    quote's own, so the cheapest scores 100 and a quote twice the price scores
    50. A quote with no technical score is not silently scored as zero: under a
    best-value RFQ it is reported as not comparable, because ranking it against
    scored quotes would compare two different things.
    """
    priced = [q for q in quotes if q.normalised_amount is not None]
    if not priced:
        return quotes
    cheapest = min(q.normalised_amount for q in priced if q.normalised_amount is not None)
    scored: list[QuoteComparison] = []
    for quote in quotes:
        amount = quote.normalised_amount
        if amount is None or amount <= 0:
            scored.append(quote)
            continue
        if quote.technical_score is None:
            scored.append(
                replace(
                    quote,
                    comparable=False,
                    normalised_amount=None,
                    reasons=(*quote.reasons, REASON_TECHNICAL_SCORE_MISSING),
                )
            )
            continue
        price_score = Decimal("100") * cheapest / amount
        total = (weight * quote.technical_score + (Decimal("100") - weight) * price_score) / Decimal("100")
        scored.append(replace(quote, price_score=price_score, total_score=total))
    return scored


def _basis_currency(rfq: dict[str, Any], bids: list[dict[str, Any]]) -> str:
    """The currency every quote is restated in.

    Normally the RFQ's own. An RFQ saved without one is already an error at
    publication (``rfq.currency_set``), and refusing to compare its quotes on
    that account would help nobody: when every quote names the same currency,
    that currency is the basis. When they disagree there is nothing to fall back
    on, and each quote is reported as unconvertible rather than ranked against
    money it is not.
    """
    stated = _text(rfq.get("currency_code")).upper()
    if stated:
        return stated
    quoted = {_text(bid.get("currency_code")).upper() for bid in bids}
    quoted.discard("")
    return quoted.pop() if len(quoted) == 1 else ""


def compare(rfq: dict[str, Any]) -> ComparisonResult:
    """Rank the quotes on an RFQ after restating them on one basis.

    Args:
        rfq: The RFQ payload built by the service: its ``currency_code``,
            ``evaluation_method``, ``technical_weight``, ``require_full_scope``,
            ``as_of``, its scope ``lines`` and its ``bids``, each with their own
            ``lines`` and ``adjustments``.

    Returns:
        The ranked quotes, the ones that could not be ranked with the reason
        for each, and which quote the comparison recommends.
    """
    bids = _rows(rfq, "bids")
    basis_currency = _basis_currency(rfq, bids)
    method = _text(rfq.get("evaluation_method")) or METHOD_LOWEST_PRICE
    require_full_scope = rfq.get("require_full_scope")
    require_full_scope = True if require_full_scope is None else bool(require_full_scope)
    required = [line for line in _rows(rfq, "lines") if not bool(line.get("is_optional"))]
    as_of = rfq.get("as_of")

    plans = _plan_plugs(bids, required, basis_currency)
    quotes = [
        _compare_one(
            bid,
            basis_currency=basis_currency,
            required=required,
            require_full_scope=require_full_scope,
            as_of=as_of,
            plugs=plans.get(_text(bid.get("id"))),
        )
        for bid in bids
    ]

    weight = _weight(rfq)
    if method == METHOD_BEST_VALUE:
        quotes = _score(quotes, weight)

    comparable = [q for q in quotes if q.comparable and q.normalised_amount is not None]
    if method == METHOD_BEST_VALUE:
        comparable.sort(
            key=lambda q: (
                -(q.total_score or Decimal("0")),
                q.normalised_amount or Decimal("0"),
                q.bidder_contact_id,
                q.bid_id,
            )
        )
    else:
        comparable.sort(
            key=lambda q: (
                q.normalised_amount or Decimal("0"),
                q.bidder_contact_id,
                q.bid_id,
            )
        )

    ranked = tuple(replace(quote, rank=position) for position, quote in enumerate(comparable, start=1))
    ranked_ids = {quote.bid_id for quote in ranked}
    excluded = tuple(quote for quote in quotes if quote.bid_id not in ranked_ids)

    return ComparisonResult(
        basis_currency=basis_currency,
        method=method,
        technical_weight=weight,
        require_full_scope=require_full_scope,
        as_of=None if as_of is None else str(as_of),
        lines_required=len(required),
        ranked=ranked,
        excluded=excluded,
        recommended_bid_id=ranked[0].bid_id if ranked else None,
    )
