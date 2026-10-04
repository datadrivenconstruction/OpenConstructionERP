# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk-based contingency: the register's expected monetary value against the
contingency the finance budget actually holds.

Pure functions only (no session, no app runtime), so every figure the
contingency card shows can be unit-tested on its own.

Vocabulary, as a project manager reads it:

* **EMV** (expected monetary value) of one risk is ``probability x cost
  impact``. The register's EMV is the sum over risks that can still happen.
  That is the *risk-based contingency*: what the register says should be set
  aside.
* **Allocated contingency** is the sum of the project's finance budget lines in
  the ``contingency`` category (revised budget, or original when no revision
  was ever booked).
* **Drawdown** is an amount a person confirmed against a contingency line when
  a risk materialised. Drawn money stays inside the project budget; it moves
  from "held for the unknown" to "spent on a known event", so remaining
  contingency is allocated minus drawn.

Which risks count toward EMV, and with what weight (:func:`risk_weight`, the
one rule the register summary, the Monte Carlo draw and this module share):

* A closed risk has been retired and drops out (weight 0).
* A risk with a confirmed drawdown drops out whatever its status says (weight
  0): its cost is already in ``drawn``, and counting it again as exposure, for
  example after it was reopened, would take the same money twice.
* An occurred risk waiting for its drawdown counts at its full impact (weight
  1). It is no longer a chance but a cost that is about to be drawn, so it must
  not make the position look better than before it occurred. Once a person
  confirms the drawdown, the confirmed amount moves into ``drawn`` and the risk
  leaves EMV, so the money is counted exactly once at every step.
* Every other status, including ``mitigated`` and ``monitoring``, still
  carries residual probability and counts at that probability.

Currency. Every amount carries its own ISO code. Amounts are converted into the
project currency with the project's own FX table (``Project.fx_rates``: units
of the project currency per one unit of the foreign one). An amount in a
currency the table has no rate for is never summed in its own units. Exposure
lands in ``unconverted_emv``, a budget line keeps its own row flagged as not
converted, and the code goes into ``missing_fx_rates``, so the totals stay
honest and the gap is visible.

P50 / P80. A deterministic read of the same register, no sampling. Each active
risk either happens (cost = impact) or not, independently. For a register small
enough the exact distribution of the total is built by convolution and the
percentile read off it. Past a size cap the normal approximation (mean = EMV,
variance = sum p(1-p)I^2) is used instead, which is where the central limit
theorem makes it reasonable. The method used is reported next to the figures so
nobody mistakes them for the Monte Carlo tab's sampled percentiles.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.core.currency_registry import money_quantum

# ── Status rule (one place, used by summary, simulation and this module) ──

#: The status of a retired risk: no exposure left at all.
CLOSED_STATUS = "closed"

#: The status that makes a risk eligible for a contingency drawdown, and makes
#: its cost certain until the drawdown is confirmed.
MATERIALISED_STATUS = "occurred"

#: The finance budget category that holds contingency (compared lower-case:
#: the manual budget form writes "Contingency", imports write "contingency").
CONTINGENCY_CATEGORY = "contingency"

#: Above this many distinct outcome totals the exact convolution is abandoned
#: for the normal approximation. 2^15 keeps the worst case well under a
#: second while covering any register a person reads line by line.
_EXACT_OUTCOME_CAP = 32_768

#: z-scores of the standard normal distribution for the percentiles we report.
_Z = {50: Decimal("0"), 80: Decimal("0.8416212335729143")}


def _status(status: str | None) -> str:
    return (status or "").strip().lower()


def risk_weight(status: str | None, probability: object, *, drawn: bool = False) -> Decimal:
    """How much of a risk's impact the register still has to carry, in [0, 1].

    Args:
        status: The risk's status.
        probability: Its probability (anything :func:`clamp_probability` reads).
        drawn: True when a person has confirmed a contingency drawdown for it.
            Only the cost side knows about drawdowns; a schedule caller leaves
            this False, because drawing money does not give the days back.

    Returns:
        0 for a closed risk or a drawn one, 1 for an occurred risk (its impact
        is certain now), and the probability for every other status.
    """
    s = _status(status)
    if drawn or s == CLOSED_STATUS:
        return Decimal("0")
    if s == MATERIALISED_STATUS:
        return Decimal("1")
    return clamp_probability(probability)


# ── Number helpers ────────────────────────────────────────────────────────


def to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    """Coerce a stored numeric (string, float, Decimal, None) to a finite Decimal."""
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError):
            return default
    if not result.is_finite():
        return default
    return result


def clamp_probability(value: object) -> Decimal:
    """Probability as a Decimal in [0, 1]; unparseable input reads as 0."""
    p = to_decimal(value)
    if p < 0:
        return Decimal("0")
    if p > 1:
        return Decimal("1")
    return p


def norm_code(code: str | None) -> str:
    """Normalised ISO currency code ("" when blank)."""
    return (code or "").strip().upper()


def fx_map_from_rates(raw: object) -> dict[str, Decimal]:
    """``Project.fx_rates`` (a list of ``{code, rate}``) as ``{CODE: Decimal}``.

    Malformed entries and non-positive rates are skipped, never guessed.
    """
    out: dict[str, Decimal] = {}
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        code = norm_code(str(entry.get("code") or ""))
        rate = to_decimal(entry.get("rate"))
        if code and rate > 0:
            out[code] = rate
    return out


def resolve_base_currency(project_currency: str | None, seen: Iterable[str]) -> str:
    """The currency the card reports in.

    The project currency when it has one. A project with none set falls back
    to the single currency every amount shares, so a register kept wholly in
    one currency still adds up; with several, the base stays blank and every
    coded amount is reported as unconverted rather than blended.
    """
    base = norm_code(project_currency)
    if base:
        return base
    codes = {norm_code(c) for c in seen if norm_code(c)}
    return next(iter(codes)) if len(codes) == 1 else ""


def convert_to_base(
    amount: Decimal,
    currency: str | None,
    *,
    base: str,
    fx: Mapping[str, Decimal],
) -> Decimal | None:
    """``amount`` in ``currency`` expressed in ``base``, or None when no rate.

    A blank code is read as the base currency (risks and budget lines inherit
    the project currency when created without one).
    """
    code = norm_code(currency)
    if not code or code == base:
        return amount
    rate = fx.get(code)
    if rate is None or rate <= 0:
        return None
    return amount * rate


def convert_from_base(
    amount: Decimal,
    currency: str | None,
    *,
    base: str,
    fx: Mapping[str, Decimal],
) -> Decimal | None:
    """Inverse of :func:`convert_to_base`: ``amount`` in ``base`` into ``currency``."""
    code = norm_code(currency)
    if not code or code == base:
        return amount
    rate = fx.get(code)
    if rate is None or rate <= 0:
        return None
    return amount / rate


def quantize_money(amount: Decimal, currency: str | None) -> Decimal:
    """Round ``amount`` to the minor unit of ``currency`` (half up)."""
    return amount.quantize(money_quantum(norm_code(currency) or None), rounding=ROUND_HALF_UP)


# ── Inputs ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RiskMoney:
    """The money-relevant view of one register row."""

    risk_id: str
    code: str
    title: str
    status: str
    probability: Decimal
    impact: Decimal
    currency: str


@dataclass(frozen=True)
class DrawdownRecord:
    """One confirmed drawdown, as stored on a contingency budget line.

    ``amount`` is in ``currency`` (the line's currency when it was confirmed).
    The risk's code and title are snapshotted so a later deletion of the risk
    cannot make the drawn money unreadable.
    """

    source: str
    risk_id: str
    amount: Decimal
    currency: str
    risk_code: str = ""
    risk_title: str = ""
    confirmed_by: str = ""
    confirmed_at: str = ""
    note: str = ""


@dataclass(frozen=True)
class ContingencyLine:
    """A finance budget line in the contingency category."""

    budget_id: str
    wbs_id: str | None
    currency: str
    allocated: Decimal
    drawdowns: Sequence[DrawdownRecord] = field(default_factory=tuple)


def allocated_amount(revised: object, original: object) -> Decimal:
    """Revised budget, or original when no revision was ever booked (both 0 -> 0)."""
    rev = to_decimal(revised)
    if rev != 0:
        return rev
    return to_decimal(original)


def parse_drawdown_record(source: str, raw: object, *, line_currency: str) -> DrawdownRecord | None:
    """Read one stored drawdown marker; None when it is not a usable record."""
    if isinstance(raw, Mapping):
        amount = to_decimal(raw.get("amount"), Decimal("-1"))
        currency = norm_code(str(raw.get("currency") or "")) or norm_code(line_currency)
        risk_id = str(raw.get("risk_id") or "")
        if not risk_id and source.startswith("risk:"):
            risk_id = source[len("risk:") :]
        if amount <= 0:
            return None
        return DrawdownRecord(
            source=source,
            risk_id=risk_id,
            amount=amount,
            currency=currency,
            risk_code=str(raw.get("risk_code") or ""),
            risk_title=str(raw.get("risk_title") or ""),
            confirmed_by=str(raw.get("confirmed_by") or ""),
            confirmed_at=str(raw.get("confirmed_at") or ""),
            note=str(raw.get("note") or ""),
        )
    amount = to_decimal(raw, Decimal("-1"))
    if amount <= 0:
        return None
    risk_id = source[len("risk:") :] if source.startswith("risk:") else ""
    return DrawdownRecord(source=source, risk_id=risk_id, amount=amount, currency=norm_code(line_currency))


# ── Percentiles ───────────────────────────────────────────────────────────


def emv_percentiles(
    outcomes: Sequence[tuple[Decimal, Decimal]],
) -> tuple[dict[int, Decimal], str]:
    """P50 and P80 of the total cost of independent yes/no risks.

    Args:
        outcomes: ``(probability, impact)`` per risk, impacts already in one
            currency and non-negative.

    Returns:
        ``({50: value, 80: value}, method)`` where method is ``"exact"`` or
        ``"normal_approximation"``. An empty input gives zeros and ``"exact"``.
    """
    live = [(p, i) for p, i in outcomes if p > 0 and i > 0]
    if not live:
        return {50: Decimal("0"), 80: Decimal("0")}, "exact"

    dist: dict[Decimal, float] = {Decimal("0"): 1.0}
    exact = True
    for p, impact in live:
        pf = float(p)
        nxt: dict[Decimal, float] = {}
        for total, weight in dist.items():
            if pf < 1.0:
                nxt[total] = nxt.get(total, 0.0) + weight * (1.0 - pf)
            hit = total + impact
            nxt[hit] = nxt.get(hit, 0.0) + weight * pf
        dist = nxt
        if len(dist) > _EXACT_OUTCOME_CAP:
            exact = False
            break

    if exact:
        ordered = sorted(dist.items())
        result: dict[int, Decimal] = {}
        for pct in (50, 80):
            target = pct / 100.0 - 1e-12
            running = 0.0
            value = ordered[-1][0]
            for total, weight in ordered:
                running += weight
                if running >= target:
                    value = total
                    break
            result[pct] = value
        return result, "exact"

    mean = sum((p * i for p, i in live), Decimal("0"))
    variance = sum((p * (1 - p) * i * i for p, i in live), Decimal("0"))
    sigma = variance.sqrt() if variance > 0 else Decimal("0")
    ceiling = sum((i for _, i in live), Decimal("0"))
    result = {}
    for pct, z in _Z.items():
        value = mean + z * sigma
        result[pct] = min(max(value, Decimal("0")), ceiling)
    return result, "normal_approximation"


# ── The position ──────────────────────────────────────────────────────────


def build_position(
    risks: Sequence[RiskMoney],
    lines: Sequence[ContingencyLine],
    *,
    project_currency: str | None,
    fx: Mapping[str, Decimal],
) -> dict[str, Any]:
    """Assemble the contingency position the risk page and finance show.

    Returns a plain dict matching :class:`app.modules.risk.schemas.ContingencyPosition`.
    """
    seen_codes = [r.currency for r in risks] + [ln.currency for ln in lines]
    for ln in lines:
        seen_codes.extend(d.currency for d in ln.drawdowns)
    base = resolve_base_currency(project_currency, seen_codes)

    drawn_risk_ids = {d.risk_id for ln in lines for d in ln.drawdowns if d.risk_id}

    # ── Expected monetary value ─────────────────────────────────────────
    emv_total = Decimal("0")
    emv_by_currency: dict[str, Decimal] = {}
    unconverted: dict[str, Decimal] = {}
    missing: set[str] = set()
    outcomes: list[tuple[Decimal, Decimal]] = []
    active = 0
    excluded_closed = 0
    excluded_drawn = 0
    pending: list[dict[str, Any]] = []
    for r in risks:
        drawn = r.risk_id in drawn_risk_ids
        weight = risk_weight(r.status, r.probability, drawn=drawn)
        if drawn:
            excluded_drawn += 1
            continue
        status = _status(r.status)
        if status == CLOSED_STATUS:
            excluded_closed += 1
            continue
        if status == MATERIALISED_STATUS:
            # Listed for a person to confirm, and meanwhile carried at its full
            # impact (weight 1), so the position cannot improve the moment a
            # risk materialises and before its money is drawn.
            pending.append(_pending_entry(r, base=base, fx=fx, lines=lines))
        else:
            active += 1
        impact = max(r.impact, Decimal("0"))
        emv = weight * impact
        code = norm_code(r.currency) or base
        emv_by_currency[code] = emv_by_currency.get(code, Decimal("0")) + emv
        converted_impact = convert_to_base(impact, r.currency, base=base, fx=fx)
        if converted_impact is None:
            missing.add(norm_code(r.currency))
            unconverted[norm_code(r.currency)] = unconverted.get(norm_code(r.currency), Decimal("0")) + emv
            continue
        emv_total += weight * converted_impact
        outcomes.append((weight, converted_impact))

    percentiles, method = emv_percentiles(outcomes)

    # ── Allocated, drawn, remaining ─────────────────────────────────────
    allocated_total = Decimal("0")
    drawn_total = Decimal("0")
    line_rows: list[dict[str, Any]] = []
    drawdown_rows: list[dict[str, Any]] = []
    for ln in lines:
        line_drawn = Decimal("0")
        for d in ln.drawdowns:
            amount_line = d.amount
            if norm_code(d.currency) and norm_code(ln.currency) and norm_code(d.currency) != norm_code(ln.currency):
                # The line's currency was changed after the drawdown; take the
                # record in its own currency through the base.
                via_base = convert_to_base(d.amount, d.currency, base=base, fx=fx)
                amount_line = (
                    convert_from_base(via_base, ln.currency, base=base, fx=fx) if via_base is not None else None
                )
            if amount_line is None:
                # Listed below in its own currency, left out of the line total.
                missing.add(norm_code(d.currency))
            else:
                line_drawn += amount_line
            drawdown_rows.append(
                {
                    "risk_id": d.risk_id or None,
                    "risk_code": d.risk_code,
                    "risk_title": d.risk_title,
                    "budget_id": ln.budget_id,
                    "amount": quantize_money(d.amount, d.currency),
                    "currency": d.currency,
                    "confirmed_by": d.confirmed_by or None,
                    "confirmed_at": d.confirmed_at or None,
                    "note": d.note,
                }
            )
        alloc_base = convert_to_base(ln.allocated, ln.currency, base=base, fx=fx)
        drawn_base = convert_to_base(line_drawn, ln.currency, base=base, fx=fx)
        if alloc_base is None or drawn_base is None:
            # Shown on its own row in its own currency, left out of the totals.
            missing.add(norm_code(ln.currency))
        else:
            allocated_total += alloc_base
            drawn_total += drawn_base
        line_rows.append(
            {
                "budget_id": ln.budget_id,
                "wbs_id": ln.wbs_id,
                "currency": norm_code(ln.currency) or base,
                "allocated": quantize_money(ln.allocated, ln.currency or base),
                "drawn": quantize_money(line_drawn, ln.currency or base),
                "remaining": quantize_money(ln.allocated - line_drawn, ln.currency or base),
                "converted": alloc_base is not None and drawn_base is not None,
            }
        )

    drawdown_rows.sort(key=lambda d: (d["confirmed_at"] or "", d["risk_code"]))
    remaining_total = allocated_total - drawn_total
    emv_q = quantize_money(emv_total, base)
    remaining_q = quantize_money(remaining_total, base)

    if not lines:
        state = "no_allocation"
    elif remaining_q < 0:
        state = "overdrawn"
    elif remaining_q < emv_q:
        state = "shortfall"
    else:
        state = "covered"

    return {
        "currency": base,
        "emv": emv_q,
        "p50": quantize_money(percentiles[50], base),
        "p80": quantize_money(percentiles[80], base),
        "percentile_method": method,
        "emv_by_currency": {c: quantize_money(v, c) for c, v in sorted(emv_by_currency.items())},
        "allocated": quantize_money(allocated_total, base),
        "drawn": quantize_money(drawn_total, base),
        "remaining": remaining_q,
        "coverage_gap": quantize_money(remaining_total - emv_total, base),
        "state": state,
        "active_risk_count": active,
        "excluded_closed_count": excluded_closed,
        "excluded_drawn_count": excluded_drawn,
        "unconverted_emv": {c: quantize_money(v, c) for c, v in sorted(unconverted.items()) if v != 0},
        "missing_fx_rates": sorted(c for c in missing if c),
        "lines": line_rows,
        "drawdowns": drawdown_rows,
        "pending": pending,
    }


def _pending_entry(
    r: RiskMoney,
    *,
    base: str,
    fx: Mapping[str, Decimal],
    lines: Sequence[ContingencyLine],
) -> dict[str, Any]:
    """An occurred risk waiting for a person to confirm its drawdown.

    ``proposed_amount`` is the risk's cost impact in the currency of the line
    the drawdown would land on by default (the only line, or the only line in
    the project currency). It is a proposal the dialog prefills; the person
    types the real figure.
    """
    target = default_line(lines, base)
    target_currency = norm_code(target.currency) if target is not None else ""
    proposed: Decimal | None = None
    impact = max(r.impact, Decimal("0"))
    if target is not None:
        if not target_currency or norm_code(r.currency) in ("", target_currency):
            proposed = impact
        else:
            via_base = convert_to_base(impact, r.currency, base=base, fx=fx)
            proposed = convert_from_base(via_base, target_currency, base=base, fx=fx) if via_base is not None else None
    proposal_currency = target_currency or base
    return {
        "risk_id": r.risk_id,
        "risk_code": r.code,
        "risk_title": r.title,
        "impact_cost": quantize_money(impact, r.currency or base),
        "currency": norm_code(r.currency) or base,
        "proposed_amount": quantize_money(proposed, proposal_currency) if proposed is not None else None,
        "proposed_currency": proposal_currency,
        "proposed_budget_id": target.budget_id if target is not None else None,
    }


def default_line(lines: Sequence[ContingencyLine], base: str) -> ContingencyLine | None:
    """The line a drawdown lands on when the person does not pick one.

    The only line, or else the only line in the project currency. Several
    candidates is ambiguous and returns None, so the person has to choose.
    """
    if len(lines) == 1:
        return lines[0]
    in_base = [ln for ln in lines if norm_code(ln.currency) in ("", base)]
    if len(in_base) == 1:
        return in_base[0]
    return None
