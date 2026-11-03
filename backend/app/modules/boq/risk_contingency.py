"""Monte Carlo cost risk -> contingency line in the estimate.

The cost-risk panel answers "how much could this bill cost at P80". This module
turns that answer into money in the estimate, explicitly and reversibly: the
estimator picks a percentile, sees the suggested amount with the run's
convergence verdict, confirms, and the amount lands as one ``boq.BOQMarkup``
line (category ``contingency``, fixed amount on the direct cost). The line's
metadata records the run behind it (percentile, seed, iterations, band,
correlation, a fingerprint of the risk inputs, date and who applied it), so a
later run can say how far the risk picture has moved since, and the
``boq.risk.contingency_stale`` rule can warn when the inputs changed.

Contingency here is ``P(target) - base``: the money that lifts the
deterministic direct cost to the chosen confidence level. It is never
negative; when the base already sits above the percentile the suggestion is
zero and says so.

Two sources feed the simulation. ``positions`` samples the bill's own lines
(the default). ``register`` samples the project risk register: register risks
are discrete events, so the whole percentile value of their probability
weighted cost distribution is the reserve (there is no deterministic base to
subtract), and the snapshot of the risks used is stored with the run so the
money traces back to register items.

Two modes set how the amount lands in the estimate. ``fixed`` writes the amount;
``percentage`` writes ``amount / direct cost`` as a percentage of the direct
cost, so the line follows later quantity edits.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from fastapi import HTTPException, status

from app.modules.boq import cost_risk_engine as cre
from app.modules.risk import mc_core
from app.modules.risk.contingency import clamp_probability, risk_weight

#: ``metadata.source`` of the one markup line this module owns per bill.
RISK_CONTINGENCY_SOURCE = "monte_carlo_contingency"
#: Key under the line's metadata holding the applied run.
RUN_KEY = "risk_run"
#: Earlier applications kept for undo, newest last.
PREVIOUS_KEY = "risk_run_previous"
MAX_PREVIOUS = 5

MIN_PERCENTILE = 50
MAX_PERCENTILE = 99

#: Convergence verdict -> confidence the suggestion is shown with.
_CONFIDENCE = {"converged": 0.9, "marginal": 0.7, "insufficient": 0.4}

_CENT = Decimal("0.01")
_PCT_STEP = Decimal("0.0001")

SOURCES = ("positions", "register")
MODES = ("fixed", "percentage")
#: Register statuses that take a risk out of the reserve.
CLOSED_REGISTER_STATUSES = frozenset({"closed", "retired", "rejected"})
#: Longer snapshots keep ids only, so the markup metadata stays small.
MAX_SNAPSHOT_ITEMS = 200
#: A percentage line is stale when the re-run differs from its current value by more than this share.
PERCENTAGE_DRIFT_TOLERANCE = Decimal("0.01")


def money(value: float | Decimal) -> Decimal:
    """Round to cents the way every BOQ money string is rounded."""
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def risk_seed(boq_id: uuid.UUID) -> int:
    """Deterministic per-BOQ seed; the cost-risk endpoint uses the same one."""
    return (boq_id.int % 2_000_000_000) or 1


def risk_inputs(positions: list[Any]) -> list[cre.PositionInput]:
    """Priced lines (those with a unit) as engine inputs, exactly as the cost-risk endpoint feeds them."""
    return [
        cre.PositionInput(ordinal=p.ordinal, description=p.description or "", base=float(p.total))
        for p in positions
        if getattr(p, "unit", None) and str(p.unit).strip() != ""
    ]


def risk_fingerprint(inputs: list[cre.PositionInput]) -> str:
    """Stable hash of what the simulation samples: every line's ordinal and three-point band.

    Order-independent, cent-rounded, so a re-save that changes nothing does not
    read as a changed risk picture.
    """

    def _r(v: float | None) -> str:
        return "" if v is None else str(money(v))

    rows = sorted(f"{p.ordinal}|{_r(p.base)}|{_r(p.low)}|{_r(p.mode)}|{_r(p.high)}|{p.distribution}" for p in inputs)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:32]


@dataclass(slots=True)
class RunParams:
    """The knobs of one simulation run."""

    percentile: int
    iterations: int = cre.DEFAULT_ITERATIONS
    optimistic_pct: float = 15.0
    pessimistic_pct: float = 25.0
    correlation: float = cre.DEFAULT_CORRELATION
    source: Literal["positions", "register"] = "positions"
    mode: Literal["fixed", "percentage"] = "fixed"

    def checked(self) -> RunParams:
        """Refuse a percentile outside the band a contingency can sensibly be set at."""
        if self.source not in SOURCES or self.mode not in MODES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown source or mode")
        if not MIN_PERCENTILE <= int(self.percentile) <= MAX_PERCENTILE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Percentile must be between {MIN_PERCENTILE} and {MAX_PERCENTILE}",
            )
        return self


@dataclass(slots=True)
class Suggestion:
    """What applying a contingency at one percentile would write."""

    percentile: int
    amount: Decimal
    pct_of_base: float
    base_total: Decimal
    budget: Decimal
    below_base: bool
    iterations: int
    seed: int
    optimistic_pct: float
    pessimistic_pct: float
    correlation: float
    convergence_status: str
    convergence_margin_pct: float
    prob_within_base: float
    confidence: float
    fingerprint: str
    source: str = "positions"
    mode: str = "fixed"
    #: Direct cost the percentage refers to (set by the service).
    direct_cost: Decimal | None = None
    #: ``amount / direct_cost * 100`` at 4 dp, only in percentage mode.
    percentage: Decimal | None = None
    #: Register source: how many risks fed the run, and their snapshot.
    items_used: int | None = None
    risk_items: list[dict[str, Any]] | None = None
    register_fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON shape of the API."""
        return {
            "percentile": self.percentile,
            "amount": self.amount,
            "pct_of_base": self.pct_of_base,
            "base_total": self.base_total,
            "budget": self.budget,
            "below_base": self.below_base,
            "iterations": self.iterations,
            "seed": self.seed,
            "optimistic_pct": self.optimistic_pct,
            "pessimistic_pct": self.pessimistic_pct,
            "correlation": self.correlation,
            "convergence_status": self.convergence_status,
            "convergence_margin_pct": self.convergence_margin_pct,
            "prob_within_base": self.prob_within_base,
            "confidence": self.confidence,
            "fingerprint": self.fingerprint,
            "source": self.source,
            "mode": self.mode,
            "direct_cost": self.direct_cost,
            "percentage": self.percentage,
            "items_used": self.items_used,
            "register_fingerprint": self.register_fingerprint,
        }


# ── Register source ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class RegisterRisk:
    """One open register risk as the simulation and the provenance snapshot see it."""

    id: str
    code: str
    title: str
    probability: str
    impact_cost: str
    currency: str
    status: str
    triple: tuple[float, float, float]
    weight: float

    @property
    def contributes(self) -> bool:
        """True when the risk can add money to the reserve."""
        return self.weight > 0.0 and max(self.triple) > 0.0

    def snapshot(self) -> dict[str, Any]:
        """The provenance row stored with a run."""
        return {
            "id": self.id,
            "code": self.code,
            "title": self.title,
            "probability": self.probability,
            "impact_cost": self.impact_cost,
            "currency": self.currency,
        }


def register_risks(rows: list[Any]) -> list[RegisterRisk]:
    """Open risks of the register (not closed, retired or rejected), weighted like the project simulation."""
    out: list[RegisterRisk] = []
    for row in rows:
        state = str(row.status or "").strip().lower()
        if state in CLOSED_REGISTER_STATUSES:
            continue
        if row.probability_score is not None:
            probability: object = max(0.0, min(float(row.probability_score) / 5.0, 1.0))
        else:
            probability = clamp_probability(row.probability)
        triple = mc_core.pert_triple_or_point(
            row.cost_p10, row.cost_p50, row.cost_p90, fallback=mc_core.safe_float(row.impact_cost)
        )
        out.append(
            RegisterRisk(
                id=str(row.id),
                code=str(row.code or ""),
                title=str(row.title or ""),
                probability=str(row.probability),
                impact_cost=str(row.impact_cost),
                currency=str(row.currency or "").strip(),
                status=state,
                triple=triple,
                weight=float(risk_weight(state, probability)),
            )
        )
    return out


def register_fingerprint(risks: list[RegisterRisk]) -> str:
    """sha1 over every open risk's id, probability, cost and status (and its three-point band).

    The band is part of it because it is what the draw samples; a risk whose
    band moved changes the reserve as much as one whose probability did.
    """
    rows = sorted(
        f"{r.id}|{r.probability}|{r.impact_cost}|{r.status}|{'/'.join(f'{v:.2f}' for v in r.triple)}" for r in risks
    )
    return hashlib.sha1("\n".join(rows).encode("utf-8"), usedforsecurity=False).hexdigest()


def _converged(totals: list[float], pct: int) -> tuple[str, float]:
    """Verdict from how far the two halves of the run disagree at the chosen percentile."""
    half = len(totals) // 2
    if half < 50:
        return "insufficient", 100.0
    a = mc_core.quantile(sorted(totals[:half]), pct / 100.0)
    b = mc_core.quantile(sorted(totals[half:]), pct / 100.0)
    mean = (a + b) / 2.0
    margin = abs(a - b) / mean * 100.0 if mean > 0 else 0.0
    return ("converged" if margin < 1.0 else "marginal" if margin < 3.0 else "insufficient"), margin


def register_suggestion(
    risks: list[RegisterRisk], params: RunParams, seed: int, direct_cost: Decimal, project_currency: str
) -> Suggestion:
    """The reserve the register asks for at ``params.percentile``.

    The amount is the whole percentile of the register's cost distribution, not
    that value minus a P50: register risks are discrete events, so every unit of
    the percentile is money that has to be held. Each draw is weighted by the
    risk's probability, exactly as the project simulation does, so a risk with
    no three-point band contributes its expected loss and only banded risks
    spread the distribution.
    """
    params.checked()
    used = [r for r in risks if r.contributes]
    if not used:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The risk register has no open priced risks"
        )
    currencies = {r.currency.upper() for r in used if r.currency}
    if len(currencies) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Risk items use more than one currency"
        )
    if currencies and project_currency and next(iter(currencies)) != project_currency.upper():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Risk items currency differs from the bill currency",
        )
    sim = mc_core.simulate_cost([mc_core.CostItem(*r.triple, r.weight) for r in used], params.iterations, seed)
    value = sim.percentile(params.percentile) or 0.0
    amount = money(value)
    base = money(direct_cost)
    verdict, margin = _converged(sim.totals, int(params.percentile))
    fingerprint = register_fingerprint(risks)
    snapshot = [r.snapshot() for r in used] if len(used) <= MAX_SNAPSHOT_ITEMS else [{"id": r.id} for r in used]
    return Suggestion(
        percentile=int(params.percentile),
        amount=amount,
        pct_of_base=round(float(amount / base * 100), 2) if base > 0 else 0.0,
        base_total=base,
        budget=base + amount,
        below_base=False,
        iterations=sim.iterations,
        seed=seed,
        optimistic_pct=params.optimistic_pct,
        pessimistic_pct=params.pessimistic_pct,
        correlation=params.correlation,
        convergence_status=verdict,
        convergence_margin_pct=round(margin, 2),
        prob_within_base=0.0,
        confidence=_CONFIDENCE.get(verdict, 0.4),
        fingerprint=fingerprint,
        source="register",
        mode=params.mode,
        items_used=len(used),
        risk_items=snapshot,
        register_fingerprint=fingerprint,
    )


def percentage_of(amount: Decimal, direct_cost: Decimal) -> Decimal:
    """``amount / direct_cost * 100`` at 4 dp; refuses a bill that cannot carry a percentage line."""
    if direct_cost <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The bill has no direct cost to take a percentage of",
        )
    pct = (amount / direct_cost * 100).quantize(_PCT_STEP, rounding=ROUND_HALF_UP)
    if pct > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The contingency exceeds the direct cost"
        )
    return pct


def suggest(inputs: list[cre.PositionInput], params: RunParams, seed: int) -> Suggestion:
    """Run the simulation and read the contingency needed to reach ``params.percentile``."""
    params.checked()
    result = cre.simulate(
        inputs,
        iterations=params.iterations,
        optimistic_pct=params.optimistic_pct,
        pessimistic_pct=params.pessimistic_pct,
        correlation=params.correlation,
        seed=seed,
        target_confidence=int(params.percentile),
    )
    base = money(result.base_total)
    budget = money(result.recommended_budget)
    raw = budget - base
    amount = raw if raw > 0 else Decimal("0.00")
    return Suggestion(
        percentile=int(params.percentile),
        amount=amount,
        pct_of_base=round(float(amount / base * 100), 2) if base > 0 else 0.0,
        base_total=base,
        budget=budget,
        below_base=raw < 0,
        iterations=result.iterations,
        seed=result.seed,
        optimistic_pct=params.optimistic_pct,
        pessimistic_pct=params.pessimistic_pct,
        correlation=round(result.correlation, 2),
        convergence_status=result.convergence_status,
        convergence_margin_pct=round(result.convergence_margin_pct, 2),
        prob_within_base=round(result.prob_within_base, 1),
        confidence=_CONFIDENCE.get(result.convergence_status, 0.4),
        fingerprint=risk_fingerprint(inputs),
    )


def run_record(s: Suggestion, *, user_id: str, user_email: str | None, now: datetime | None = None) -> dict[str, Any]:
    """The provenance stored on the markup line for one application."""
    record: dict[str, Any] = {
        "percentile": s.percentile,
        "amount": str(s.amount),
        "pct_of_base": s.pct_of_base,
        "base_total": str(s.base_total),
        "budget": str(s.budget),
        "seed": s.seed,
        "iterations": s.iterations,
        "optimistic_pct": s.optimistic_pct,
        "pessimistic_pct": s.pessimistic_pct,
        "correlation": s.correlation,
        "convergence_status": s.convergence_status,
        "confidence": s.confidence,
        "fingerprint": s.fingerprint,
        "source": s.source,
        "mode": s.mode,
        "percentage": str(s.percentage) if s.percentage is not None else None,
        "applied_at": (now or datetime.now(UTC)).isoformat(),
        "applied_by": user_id,
        "applied_by_email": user_email,
    }
    if s.source == "register":
        record["items_used"] = s.items_used
        record["risk_items"] = s.risk_items or []
        record["register_fingerprint"] = s.register_fingerprint
    return record


def params_of(record: dict[str, Any]) -> RunParams:
    """The parameters an applied run was made with, to re-run it like for like."""
    return RunParams(
        percentile=int(record.get("percentile") or 80),
        iterations=int(record.get("iterations") or cre.DEFAULT_ITERATIONS),
        optimistic_pct=float(record.get("optimistic_pct") or 0.0),
        pessimistic_pct=float(record.get("pessimistic_pct") or 0.0),
        correlation=float(record.get("correlation") or 0.0),
        source="register" if record.get("source") == "register" else "positions",
        mode="percentage" if record.get("mode") == "percentage" else "fixed",
    )


def record_source(record: dict[str, Any]) -> str:
    """Source of an applied run; runs stored before the register source existed are ``positions``."""
    return "register" if record.get("source") == "register" else "positions"


def line_amount(line: Any, direct_cost: Decimal) -> Decimal:
    """The money the risk line adds to the bill right now."""
    if getattr(line, "markup_type", "fixed") == "percentage":
        return money(direct_cost * Decimal(str(line.percentage or "0")) / 100)
    return money(Decimal(str(line.fixed_amount or "0")))


def export_label(name: str, metadata: Any) -> str:
    """Name of a markup line as exports print it; risk lines say which run and source they come from."""
    record = metadata.get(RUN_KEY) if isinstance(metadata, dict) else None
    if not isinstance(record, dict) or not record.get("percentile"):
        return name
    if record_source(record) == "register":
        return f"{name} (P{record['percentile']} from risk register, {record.get('items_used') or 0} items)"
    return f"{name} (P{record['percentile']} risk allowance, run {record.get('seed')})"


def is_risk_line(markup: Any) -> bool:
    """True for the markup line this module wrote."""
    meta = getattr(markup, "metadata_", None)
    if meta is None and isinstance(markup, dict):
        meta = markup.get("metadata")
    return isinstance(meta, dict) and meta.get("source") == RISK_CONTINGENCY_SOURCE


def find_risk_line(markups: list[Any]) -> Any | None:
    """The bill-wide risk contingency line, if one was applied."""
    for m in markups:
        if is_risk_line(m) and not getattr(m, "scope_position_id", None):
            return m
    return None


def drift(applied: dict[str, Any], current_amount: Decimal) -> tuple[Decimal, float | None]:
    """Signed change of the contingency a like-for-like re-run would suggest now."""
    try:
        before = Decimal(str(applied.get("amount") or "0"))
    except ArithmeticError:
        before = Decimal("0")
    delta = money(current_amount - before)
    pct = round(float(delta / before * 100), 2) if before > 0 else None
    return delta, pct


def is_stale(
    record: dict[str, Any],
    current_fingerprint: str,
    *,
    line_value: Decimal | None = None,
    rerun_amount: Decimal | None = None,
) -> bool:
    """Whether the risk picture behind an applied line has moved.

    A fixed line is stale when its source's fingerprint changed. A percentage line
    follows quantities by design, so on the bill's own positions only the
    re-simulated amount against its current value counts; on the register the
    fingerprint counts too.
    """
    by_drift = bool(
        record.get("mode") == "percentage"
        and line_value is not None
        and rerun_amount is not None
        and abs(rerun_amount - line_value) > max(_CENT, abs(line_value) * PERCENTAGE_DRIFT_TOLERANCE)
    )
    if record.get("mode") == "percentage" and record_source(record) == "positions":
        return by_drift
    return record.get("fingerprint") != current_fingerprint or by_drift


def stale_block(
    markups: list[Any],
    inputs: list[cre.PositionInput],
    *,
    register_fp: str | None = None,
    line_value: Decimal | None = None,
    rerun_amount: Decimal | None = None,
) -> dict[str, Any] | None:
    """What the ``boq.risk.contingency_stale`` rule reads; ``None`` when nothing was applied.

    A hash compare unless the caller supplies a re-run, so Validate stays quick
    for fixed lines. ``register_fp`` is the register's current fingerprint and
    is used when the applied run came from the register.
    """
    line = find_risk_line(markups)
    if line is None or not getattr(line, "is_active", True):
        return None
    meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
    record = meta.get(RUN_KEY) if isinstance(meta.get(RUN_KEY), dict) else {}
    source = record_source(record)
    current = (register_fp or "") if source == "register" else risk_fingerprint(inputs)
    return {
        "markup_id": str(line.id),
        "name": line.name,
        "percentile": record.get("percentile"),
        "amount": record.get("amount"),
        "applied_at": record.get("applied_at"),
        "applied_fingerprint": record.get("fingerprint"),
        "current_fingerprint": current,
        "source": source,
        "mode": record.get("mode") or "fixed",
        "line_amount": str(line_value) if line_value is not None else None,
        "stale": is_stale(record, current, line_value=line_value, rerun_amount=rerun_amount),
    }


def next_metadata(
    existing: dict[str, Any] | None,
    record: dict[str, Any],
    line_fixed_amount: str | None,
    *,
    line_type: str | None = None,
    line_percentage: str | None = None,
) -> dict:
    """Metadata of the line after a new application, keeping the previous one for undo."""
    meta = dict(existing or {})
    previous = list(meta.get(PREVIOUS_KEY) or [])
    if isinstance(meta.get(RUN_KEY), dict):
        prev = dict(meta[RUN_KEY])
        if line_fixed_amount is not None:
            prev["line_amount"] = line_fixed_amount
        if line_type is not None:
            prev["line_type"] = line_type
            prev["line_percentage"] = line_percentage or "0"
        previous.append(prev)
    meta["source"] = RISK_CONTINGENCY_SOURCE
    meta[RUN_KEY] = record
    meta[PREVIOUS_KEY] = previous[-MAX_PREVIOUS:]
    return meta


def undo_state(existing: dict[str, Any]) -> tuple[dict[str, Any], str, str, str] | None:
    """Metadata, fixed amount, line type and percentage after undoing the last application.

    ``None`` means there is nothing to step back to and the line goes.
    """
    previous = list(existing.get(PREVIOUS_KEY) or [])
    if not previous:
        return None
    restored = dict(previous.pop())
    amount = str(restored.pop("line_amount", restored.get("amount") or "0"))
    line_type = str(restored.pop("line_type", "fixed"))
    percentage = str(restored.pop("line_percentage", "0"))
    meta = dict(existing)
    meta[RUN_KEY] = restored
    meta[PREVIOUS_KEY] = previous
    return meta, amount, line_type, percentage


def undo_metadata(existing: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Metadata and amount after undoing the last application; ``(None, None)`` means remove the line."""
    state = undo_state(existing)
    return (None, None) if state is None else (state[0], state[1])


# ── Orchestration over the BOQ service ──────────────────────────────────────


def _record_of(line: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
    record = meta.get(RUN_KEY) if isinstance(meta.get(RUN_KEY), dict) else {}
    return meta, record


def _applied_view(line: Any, direct_cost: Decimal) -> dict[str, Any]:
    meta, record = _record_of(line)
    keep = (
        "amount",
        "pct_of_base",
        "base_total",
        "seed",
        "iterations",
        "optimistic_pct",
        "pessimistic_pct",
        "correlation",
        "convergence_status",
        "fingerprint",
        "applied_at",
        "applied_by",
        "applied_by_email",
        "percentage",
        "items_used",
        "risk_items",
        "register_fingerprint",
    )
    return {
        "markup_id": line.id,
        "name": line.name,
        "is_active": bool(line.is_active),
        "line_amount": str(line_amount(line, direct_cost)),
        "percentile": int(record.get("percentile") or 0),
        "source": record_source(record),
        "mode": "percentage" if getattr(line, "markup_type", "fixed") == "percentage" else "fixed",
        **{k: record.get(k) for k in keep},
        "can_undo_to_previous": bool(meta.get(PREVIOUS_KEY)),
    }


@dataclass(slots=True)
class _Context:
    """Everything one run reads from the bill (and the register) so it is loaded once."""

    inputs: list[cre.PositionInput]
    direct_cost: Decimal
    currency: str
    risks: list[RegisterRisk] | None

    def fingerprint(self, source: str) -> str:
        """Fingerprint of the inputs a run of ``source`` samples."""
        return register_fingerprint(self.risks or []) if source == "register" else risk_fingerprint(self.inputs)


class RiskContingencyService:
    """Preview, apply and undo a risk contingency on one bill.

    Every write goes through ``BOQService`` markup methods, so the bill's lock,
    events and audit apply exactly as for a line typed in the markups panel.
    """

    def __init__(self, boq_service: Any) -> None:
        self.boq = boq_service

    async def _context(self, boq_id: uuid.UUID, *, register: bool, data: Any = None) -> _Context:
        data = data or await self.boq.get_boq_with_positions(boq_id)
        risks: list[RegisterRisk] | None = None
        currency = ""
        if register:
            from app.modules.risk.repository import RiskRepository  # noqa: PLC0415 - only the register source needs it

            risks = register_risks(await RiskRepository(self.boq.session).all_for_project(data.project_id))
            currency = (await self.boq.get_export_fx(boq_id))[0]
        return _Context(
            inputs=risk_inputs(list(data.positions)),
            direct_cost=Decimal(str(data.direct_cost_total)),
            currency=currency,
            risks=risks,
        )

    @staticmethod
    def _suggest(ctx: _Context, params: RunParams, seed: int, *, strict: bool = True) -> Suggestion:
        """One run for ``params``; ``strict=False`` leaves the percentage empty on a bill that cannot carry one."""
        if params.source == "register":
            s = register_suggestion(ctx.risks or [], params, seed, ctx.direct_cost, ctx.currency)
        else:
            s = suggest(ctx.inputs, params, seed)
            s.mode = params.mode
        s.direct_cost = money(ctx.direct_cost)
        if params.mode == "percentage":
            try:
                s.percentage = percentage_of(s.amount, ctx.direct_cost)
            except HTTPException:
                if strict:
                    raise
        return s

    async def status(self, boq_id: uuid.UUID, params: RunParams | None) -> dict[str, Any]:
        """Suggestion for ``params`` (if given), the applied line and its drift."""
        data = await self.boq.get_boq_with_positions(boq_id)
        line = find_risk_line(await self.boq.list_markups(boq_id))
        record = _record_of(line)[1] if line is not None else {}
        applied_source = record_source(record) if line is not None else None
        register = (params is not None and params.source == "register") or applied_source == "register"
        ctx = await self._context(boq_id, register=register, data=data)
        seed = risk_seed(boq_id)
        out: dict[str, Any] = {
            "current_fingerprint": ctx.fingerprint(applied_source or (params.source if params else "positions"))
        }
        if params is not None:
            try:
                out["suggestion"] = self._suggest(ctx, params, seed, strict=False).as_dict()
            except HTTPException as exc:
                if line is None:
                    raise
                # A preview the inputs cannot back must not hide the applied line or its undo.
                out["suggestion_error"] = str(exc.detail)
        if line is not None:
            out["applied"] = _applied_view(line, ctx.direct_cost)
            value = line_amount(line, ctx.direct_cost)
            rerun_amount: Decimal | None = None
            if record:
                try:
                    rerun_amount = self._suggest(
                        ctx, params_of(record), int(record.get("seed") or seed), strict=False
                    ).amount
                except HTTPException:
                    rerun_amount = None  # the register emptied since: nothing to compare with
            out["stale"] = is_stale(record, out["current_fingerprint"], line_value=value, rerun_amount=rerun_amount)
            if rerun_amount is not None:
                was = value if record.get("mode") == "percentage" else Decimal(str(record.get("amount") or "0"))
                delta, pct = drift({"amount": str(was)}, rerun_amount)
                out["drift_amount"] = str(delta)
                out["drift_pct"] = pct
        return out

    async def rule_block(self, boq_id: uuid.UUID, data: Any, markups: list[Any]) -> dict[str, Any] | None:
        """Facts for the ``boq.risk.*`` rules; ``None`` when no active risk line exists."""
        line = find_risk_line(markups)
        if line is None or not getattr(line, "is_active", True):
            return None
        record = _record_of(line)[1]
        source = record_source(record)
        ctx = await self._context(boq_id, register=source == "register", data=data)
        value = line_amount(line, ctx.direct_cost)
        params = params_of(record)
        seed = int(record.get("seed") or risk_seed(boq_id))
        rerun_amount: Decimal | None = None
        p50_amount: Decimal | None = None
        try:
            if params.mode == "percentage":
                rerun_amount = self._suggest(ctx, params, seed, strict=False).amount
            p50_amount = self._suggest(ctx, replace(params, percentile=MIN_PERCENTILE), seed, strict=False).amount
        except HTTPException:
            pass  # an emptied register leaves the fingerprint compare to say the line is stale
        block = stale_block(
            markups,
            ctx.inputs,
            register_fp=ctx.fingerprint("register") if source == "register" else None,
            line_value=value,
            rerun_amount=rerun_amount,
        )
        if block is None:
            return None
        block["p50_amount"] = str(p50_amount) if p50_amount is not None else None
        block["line_amount"] = str(value)
        block["other_contingency"] = [
            str(m.name)
            for m in markups
            if getattr(m, "is_active", True) and m.category == "contingency" and not is_risk_line(m)
        ]
        return block

    async def apply(
        self,
        boq_id: uuid.UUID,
        params: RunParams,
        *,
        user_id: str,
        user_email: str | None,
        expected_amount: Decimal | None,
        name: str | None,
    ) -> dict[str, Any]:
        """Write the contingency line from a fresh, server-side run."""
        from app.modules.boq.schemas import MarkupCreate, MarkupUpdate  # noqa: PLC0415 - avoid import cycle

        params.checked()
        ctx = await self._context(boq_id, register=params.source == "register")
        if params.source == "positions" and (not ctx.inputs or sum(p.base for p in ctx.inputs) <= 0):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The bill has no priced lines to simulate",
            )
        s = self._suggest(ctx, params, risk_seed(boq_id))
        if expected_amount is not None and abs(money(expected_amount) - s.amount) > _CENT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"The bill changed since the preview: the contingency is now {s.amount}. Review and confirm again.",
            )
        record = run_record(s, user_id=user_id, user_email=user_email)
        label = (name or "").strip() or f"Risk contingency P{s.percentile}"
        record["name"] = label
        by_percentage = params.mode == "percentage" and s.percentage is not None
        markups = await self.boq.list_markups(boq_id)
        line = find_risk_line(markups)
        if line is None:
            orders = [int(m.sort_order or 0) for m in markups if not m.scope_position_id]
            # First in the stack so cumulative lines (tax) compound on it; 0 would mean "append".
            first = min(orders) - 1 if orders and min(orders) > 1 else 0
            await self.boq.add_markup(
                boq_id,
                MarkupCreate(
                    name=label,
                    markup_type="percentage" if by_percentage else "fixed",
                    category="contingency",
                    percentage=float(s.percentage) if by_percentage else 0.0,
                    fixed_amount=Decimal("0") if by_percentage else s.amount,
                    apply_to="direct_cost",
                    sort_order=first,
                    metadata=next_metadata(None, record, None),
                ),
            )
        else:
            meta = _record_of(line)[0]
            await self.boq.update_markup(
                line.id,
                MarkupUpdate(
                    name=label,
                    markup_type="percentage" if by_percentage else "fixed",
                    percentage=float(s.percentage) if by_percentage else 0.0,
                    fixed_amount=Decimal("0") if by_percentage else s.amount,
                    apply_to="direct_cost",
                    is_active=True,
                    metadata=next_metadata(
                        meta,
                        record,
                        str(line.fixed_amount or "0"),
                        line_type=str(line.markup_type),
                        line_percentage=str(line.percentage or "0"),
                    ),
                ),
            )
        return await self.status(boq_id, params)

    async def undo(self, boq_id: uuid.UUID) -> dict[str, Any]:
        """Restore the previous application, or remove the line when there was none."""
        from app.modules.boq.schemas import MarkupUpdate  # noqa: PLC0415 - avoid import cycle

        line = find_risk_line(await self.boq.list_markups(boq_id))
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No risk contingency applied")
        state = undo_state(_record_of(line)[0])
        if state is None:
            await self.boq.delete_markup(line.id)
        else:
            restored, amount, line_type, percentage = state
            by_percentage = line_type == "percentage"
            await self.boq.update_markup(
                line.id,
                MarkupUpdate(
                    name=str(restored.get(RUN_KEY, {}).get("name") or line.name),
                    markup_type="percentage" if by_percentage else "fixed",
                    percentage=float(percentage) if by_percentage else 0.0,
                    fixed_amount=Decimal("0") if by_percentage else Decimal(amount or "0"),
                    metadata=restored,
                ),
            )
        return await self.status(boq_id, None)
