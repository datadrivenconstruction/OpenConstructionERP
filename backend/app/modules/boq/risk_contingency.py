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
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status

from app.modules.boq import cost_risk_engine as cre

#: ``metadata.source`` of the one markup line this module owns per bill.
RISK_CONTINGENCY_SOURCE = "monte_carlo_contingency"
#: Key under the line's metadata holding the applied run.
RUN_KEY = "risk_run"
#: Earlier applications kept for undo, newest last.
PREVIOUS_KEY = "risk_run_previous"
MAX_PREVIOUS = 5

#: ``mode`` of the written line. ``fixed`` holds the money as typed; ``percentage`` stores
#: contingency / direct cost so the amount follows later quantity edits.
MODE_FIXED = "fixed"
MODE_PERCENTAGE = "percentage"
MODES = (MODE_FIXED, MODE_PERCENTAGE)

MIN_PERCENTILE = 50
MAX_PERCENTILE = 99

#: Convergence verdict -> confidence the suggestion is shown with.
_CONFIDENCE = {"converged": 0.9, "marginal": 0.7, "insufficient": 0.4}

_CENT = Decimal("0.01")


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

    def checked(self) -> RunParams:
        """Refuse a percentile outside the band a contingency can sensibly be set at."""
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
    #: Contingency that reaches only the median (P50 - base, never negative).
    p50_amount: Decimal = Decimal("0.00")

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
            "p50_amount": self.p50_amount,
        }


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
    p50_raw = money(result.percentiles.get("p50", result.base_total)) - base
    p50_amount = p50_raw if p50_raw > 0 else Decimal("0.00")
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
        p50_amount=p50_amount,
    )


def run_record(
    s: Suggestion,
    *,
    user_id: str,
    user_email: str | None,
    now: datetime | None = None,
    mode: str = MODE_FIXED,
    percentage: float | None = None,
    scope_position_id: str | None = None,
) -> dict[str, Any]:
    """The provenance stored on the markup line for one application."""
    return {
        "mode": mode,
        "percentage": percentage,
        "scope_position_id": scope_position_id,
        "p50_amount": str(s.p50_amount),
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
        "applied_at": (now or datetime.now(UTC)).isoformat(),
        "applied_by": user_id,
        "applied_by_email": user_email,
    }


def params_of(record: dict[str, Any]) -> RunParams:
    """The parameters an applied run was made with, to re-run it like for like."""
    return RunParams(
        percentile=int(record.get("percentile") or 80),
        iterations=int(record.get("iterations") or cre.DEFAULT_ITERATIONS),
        optimistic_pct=float(record.get("optimistic_pct") or 0.0),
        pessimistic_pct=float(record.get("pessimistic_pct") or 0.0),
        correlation=float(record.get("correlation") or 0.0),
    )


def section_positions(positions: list[Any], section_id: uuid.UUID) -> list[Any]:
    """The positions under one section (itself included), by the parent chain."""
    ids = {str(section_id)}
    if not any(str(p.id) in ids for p in positions):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found in this bill")
    grew = True
    while grew:
        grew = False
        for p in positions:
            if p.parent_id is not None and str(p.parent_id) in ids and str(p.id) not in ids:
                ids.add(str(p.id))
                grew = True
    return [p for p in positions if str(p.id) in ids]


def is_risk_line(markup: Any) -> bool:
    """True for the markup line this module wrote."""
    meta = getattr(markup, "metadata_", None)
    if meta is None and isinstance(markup, dict):
        meta = markup.get("metadata")
    return isinstance(meta, dict) and meta.get("source") == RISK_CONTINGENCY_SOURCE


def risk_label_parts(markup: Any) -> tuple[int, str] | None:
    """``(percentile, run id)`` for the exports' "P80 risk allowance" label, ``None`` for any other line."""
    if not is_risk_line(markup):
        return None
    meta = getattr(markup, "metadata_", None)
    record = meta.get(RUN_KEY) if isinstance(meta, dict) else None
    if not isinstance(record, dict) or not record.get("percentile"):
        return None
    run = str(record.get("fingerprint") or "")[:8] or str(record.get("seed") or "?")
    return int(record["percentile"]), run


def find_risk_line(markups: list[Any], scope_position_id: Any = None) -> Any | None:
    """The risk contingency line of one scope: the bill (default) or a section."""
    want = str(scope_position_id) if scope_position_id else None
    for m in markups:
        have = getattr(m, "scope_position_id", None)
        if is_risk_line(m) and (str(have) if have else None) == want:
            return m
    return None


def other_contingency(markups: list[Any]) -> list[str]:
    """Names of active contingency lines this module did not write: a possible double count."""
    return [
        str(m.name)
        for m in markups
        if getattr(m, "is_active", True) and getattr(m, "category", "") == "contingency" and not is_risk_line(m)
    ]


def line_amount(line: Any, base_total: Decimal) -> Decimal:
    """Money the line adds today: its fixed amount, or its percentage of the direct cost."""
    if getattr(line, "markup_type", MODE_FIXED) == MODE_PERCENTAGE:
        return money(base_total * Decimal(str(line.percentage or 0)) / Decimal("100"))
    return money(line.fixed_amount or 0)


def percentage_of(amount: Decimal, base_total: Decimal) -> float:
    """Contingency as a percent of the direct cost, for the percentage mode."""
    if base_total <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The bill has no direct cost to take a percentage of",
        )
    pct = round(float(amount / base_total * 100), 4)
    if pct > 100.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The contingency exceeds 100% of the direct cost; keep it as a fixed amount",
        )
    return pct


def drift(applied: dict[str, Any], current_amount: Decimal) -> tuple[Decimal, float | None]:
    """Signed change of the contingency a like-for-like re-run would suggest now."""
    try:
        before = Decimal(str(applied.get("amount") or "0"))
    except ArithmeticError:
        before = Decimal("0")
    delta = money(current_amount - before)
    pct = round(float(delta / before * 100), 2) if before > 0 else None
    return delta, pct


def stale_block(markups: list[Any], inputs: list[cre.PositionInput]) -> dict[str, Any] | None:
    """What the ``boq.risk.contingency_stale`` rule reads; ``None`` when nothing was applied.

    Cheap on purpose (a hash, no simulation): it runs on every Validate click.
    """
    line = find_risk_line(markups)
    if line is None or not getattr(line, "is_active", True):
        return None
    meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
    record = meta.get(RUN_KEY) if isinstance(meta.get(RUN_KEY), dict) else {}
    current = risk_fingerprint(inputs)
    base_total = money(sum(p.base for p in inputs))
    try:
        p50_amount = Decimal(str(record.get("p50_amount"))) if record.get("p50_amount") is not None else None
    except ArithmeticError:
        p50_amount = None
    today = line_amount(line, base_total)
    return {
        "line_amount": str(today),
        "p50_amount": str(p50_amount) if p50_amount is not None else None,
        "below_p50": p50_amount is not None and today < p50_amount,
        "other_contingency": other_contingency(markups),
        "markup_id": str(line.id),
        "name": line.name,
        "percentile": record.get("percentile"),
        "amount": record.get("amount"),
        "applied_at": record.get("applied_at"),
        "applied_fingerprint": record.get("fingerprint"),
        "current_fingerprint": current,
        "stale": record.get("fingerprint") != current,
    }


def next_metadata(
    existing: dict[str, Any] | None,
    record: dict[str, Any],
    line_fixed_amount: str | None,
    line_mode: str | None = None,
    line_percentage: float | None = None,
) -> dict:
    """Metadata of the line after a new application, keeping the previous one for undo."""
    meta = dict(existing or {})
    previous = list(meta.get(PREVIOUS_KEY) or [])
    if isinstance(meta.get(RUN_KEY), dict):
        prev = dict(meta[RUN_KEY])
        if line_fixed_amount is not None:
            prev["line_amount"] = line_fixed_amount
        if line_mode is not None:
            prev["line_mode"] = line_mode
            prev["line_percentage"] = line_percentage
        previous.append(prev)
    meta["source"] = RISK_CONTINGENCY_SOURCE
    meta[RUN_KEY] = record
    meta[PREVIOUS_KEY] = previous[-MAX_PREVIOUS:]
    return meta


def undo_metadata(existing: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Metadata and amount after undoing the last application; ``(None, None)`` means remove the line."""
    previous = list(existing.get(PREVIOUS_KEY) or [])
    if not previous:
        return None, None
    restored = dict(previous.pop())
    amount = str(restored.pop("line_amount", restored.get("amount") or "0"))
    meta = dict(existing)
    meta[RUN_KEY] = restored
    meta[PREVIOUS_KEY] = previous
    return meta, amount


# ── Orchestration over the BOQ service ──────────────────────────────────────


def _applied_view(line: Any) -> dict[str, Any]:
    meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
    record = meta.get(RUN_KEY) if isinstance(meta.get(RUN_KEY), dict) else {}
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
    )
    return {
        "markup_id": line.id,
        "name": line.name,
        "is_active": bool(line.is_active),
        "line_amount": str(line.fixed_amount or "0") if line.markup_type != MODE_PERCENTAGE else record.get("amount"),
        "mode": MODE_PERCENTAGE if line.markup_type == MODE_PERCENTAGE else MODE_FIXED,
        "percentage": float(line.percentage) if line.markup_type == MODE_PERCENTAGE else None,
        "scope_position_id": line.scope_position_id,
        "percentile": int(record.get("percentile") or 0),
        **{k: record.get(k) for k in keep},
        "can_undo_to_previous": bool(meta.get(PREVIOUS_KEY)),
    }


class RiskContingencyService:
    """Preview, apply and undo a risk contingency on one bill.

    Every write goes through ``BOQService`` markup methods, so the bill's lock,
    events and audit apply exactly as for a line typed in the markups panel.
    """

    def __init__(self, boq_service: Any) -> None:
        self.boq = boq_service

    async def _inputs(self, boq_id: uuid.UUID, scope_position_id: uuid.UUID | None = None) -> list[cre.PositionInput]:
        data = await self.boq.get_boq_with_positions(boq_id)
        positions = list(data.positions)
        if scope_position_id is not None:
            positions = section_positions(positions, scope_position_id)
        return risk_inputs(positions)

    async def status(
        self,
        boq_id: uuid.UUID,
        params: RunParams | None,
        scope_position_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Suggestion for ``params`` (if given), the applied line and its drift."""
        inputs = await self._inputs(boq_id, scope_position_id)
        seed = risk_seed(boq_id)
        out: dict[str, Any] = {"current_fingerprint": risk_fingerprint(inputs)}
        if params is not None:
            out["suggestion"] = suggest(inputs, params, seed).as_dict()
        markups = await self.boq.list_markups(boq_id)
        out["other_contingency"] = other_contingency(markups)
        line = find_risk_line(markups, scope_position_id)
        if line is not None:
            view = _applied_view(line)
            out["applied"] = view
            meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
            record = meta.get(RUN_KEY) if isinstance(meta.get(RUN_KEY), dict) else {}
            out["stale"] = record.get("fingerprint") != out["current_fingerprint"]
            if record:
                rerun = suggest(inputs, params_of(record), int(record.get("seed") or seed))
                delta, pct = drift(record, rerun.amount)
                out["drift_amount"] = str(delta)
                out["drift_pct"] = pct
        return out

    async def apply(
        self,
        boq_id: uuid.UUID,
        params: RunParams,
        *,
        user_id: str,
        user_email: str | None,
        expected_amount: Decimal | None,
        name: str | None,
        mode: str = MODE_FIXED,
        scope_position_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Write the contingency line from a fresh, server-side run.

        ``mode="percentage"`` stores the contingency as a share of the direct cost, so the
        money follows later quantity edits. ``scope_position_id`` confines the run and the
        line to one section; a bill-wide risk line, if present, is overridden inside it.
        """
        from app.modules.boq.schemas import MarkupCreate, MarkupUpdate  # noqa: PLC0415 - avoid import cycle

        if mode not in MODES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown contingency mode")
        inputs = await self._inputs(boq_id, scope_position_id)
        if not inputs or sum(p.base for p in inputs) <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The bill has no priced lines to simulate",
            )
        s = suggest(inputs, params, risk_seed(boq_id))
        if expected_amount is not None and abs(money(expected_amount) - s.amount) > _CENT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"The bill changed since the preview: the contingency is now {s.amount}. Review and confirm again.",
            )
        pct = percentage_of(s.amount, s.base_total) if mode == MODE_PERCENTAGE else None
        record = run_record(
            s,
            user_id=user_id,
            user_email=user_email,
            mode=mode,
            percentage=pct,
            scope_position_id=str(scope_position_id) if scope_position_id else None,
        )
        label = (name or "").strip() or f"Risk contingency P{s.percentile}"
        record["name"] = label
        fields = {
            "markup_type": mode,
            "fixed_amount": s.amount if mode == MODE_FIXED else Decimal("0"),
            "percentage": pct if pct is not None else 0.0,
        }
        markups = await self.boq.list_markups(boq_id)
        line = find_risk_line(markups, scope_position_id)
        if line is None:
            wide = find_risk_line(markups) if scope_position_id else None
            orders = [int(m.sort_order or 0) for m in markups if not m.scope_position_id]
            # First in the stack so cumulative lines (tax) compound on it; 0 would mean "append".
            first = min(orders) - 1 if orders and min(orders) > 1 else 0
            await self.boq.add_markup(
                boq_id,
                MarkupCreate(
                    name=label,
                    category="contingency",
                    apply_to="direct_cost",
                    sort_order=int(wide.sort_order or 0) if wide is not None else first,
                    scope_position_id=scope_position_id,
                    overrides_id=wide.id if wide is not None else None,
                    metadata=next_metadata(None, record, None),
                    **fields,
                ),
            )
        else:
            meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
            await self.boq.update_markup(
                line.id,
                MarkupUpdate(
                    name=label,
                    is_active=True,
                    metadata=next_metadata(
                        meta,
                        record,
                        str(line.fixed_amount or "0"),
                        line.markup_type,
                        float(line.percentage or 0.0),
                    ),
                    **fields,
                ),
            )
        return await self.status(boq_id, params, scope_position_id)

    async def undo(self, boq_id: uuid.UUID, scope_position_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Restore the previous application, or remove the line when there was none."""
        from app.modules.boq.schemas import MarkupUpdate  # noqa: PLC0415 - avoid import cycle

        line = find_risk_line(await self.boq.list_markups(boq_id), scope_position_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No risk contingency applied")
        meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
        restored, amount = undo_metadata(meta)
        if restored is None:
            await self.boq.delete_markup(line.id)
        else:
            run = restored.get(RUN_KEY, {})
            mode = run.get("line_mode") or MODE_FIXED
            await self.boq.update_markup(
                line.id,
                MarkupUpdate(
                    name=str(run.get("name") or line.name),
                    markup_type=mode,
                    fixed_amount=Decimal(amount or "0") if mode == MODE_FIXED else Decimal("0"),
                    percentage=float(run.get("line_percentage") or 0.0) if mode == MODE_PERCENTAGE else 0.0,
                    metadata=restored,
                ),
            )
        return await self.status(boq_id, None, scope_position_id)
