# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Foreman productivity: what a crew installed for the hours it booked, against the norm.

Post-calculation answers "did the job beat its estimate" once, over the whole
life of a bill. A foreman asks the same question every week about the work in
front of him: on each bill position, how much went in this period, how many
hours it took, how that compares with the norm the estimate was priced on, and
how many hours are left at the rate the crew is actually running.

Nothing here is a second definition of a figure another module owns:

* the estimate norm is the bill baseline post-calculation uses, the per-unit
  labour and plant hours of the resource split stored on the position
  (:func:`app.modules.postcalc.service._per_unit_hours`), and the on-plan /
  over / under verdict is the post-calculation classifier with its tolerance;
* hours are the counted timesheets (:mod:`app.modules.field_time.counted`);
* installed quantity is the measurement book where a position has
  measurements, otherwise the progress module's latest percent of the planned
  quantity. A disputed measurement does not count; a checker's re-measure
  replaces the measured figure.

The productivity factor is spent hours over earned hours (installed quantity
times the norm), so above 1 the crew is slower than the norm. Groups are summed
numerator over summed denominator, never averaged.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HOURS_Q = Decimal("0.01")
_QTY_Q = Decimal("0.0001")
_FACTOR_Q = Decimal("0.001")

#: A factor within this fraction of 1.0 is on plan (same default as post-calculation).
DEFAULT_TOLERANCE = Decimal("0.05")
#: Beyond three tolerances the light turns red rather than amber.
_AMBER_MULTIPLE = Decimal("3")
#: Outside this band a factor is more likely a booking or unit error than site reality.
DEFAULT_PLAUSIBLE_LOW = Decimal("0.5")
DEFAULT_PLAUSIBLE_HIGH = Decimal("2.0")
#: Longest period one request may cover; a season is plenty for a foreman view.
MAX_PERIOD_DAYS = 370

LIGHT_GREEN = "green"
LIGHT_AMBER = "amber"
LIGHT_RED = "red"
LIGHT_GREY = "grey"


def _dec(value: object) -> Decimal:
    """Coerce a stored value to a finite Decimal; anything unreadable is zero."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else _ZERO
    if value is None or value == "":
        return _ZERO
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO
    return out if out.is_finite() else _ZERO


def _s(value: Decimal | None, quant: Decimal) -> str | None:
    return None if value is None else str(value.quantize(quant))


def week_start(day: date) -> date:
    """Monday of the ISO week holding ``day``."""
    return day - timedelta(days=day.weekday())


def period_weeks(date_from: date, date_to: date) -> list[date]:
    """Monday of every ISO week the period touches, in order."""
    out: list[date] = []
    cur = week_start(date_from)
    while cur <= date_to:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def classify(factor: Decimal, tolerance: Decimal = DEFAULT_TOLERANCE) -> str:
    """The post-calculation verdict for a factor, so both screens say the same word."""
    from app.modules.postcalc.service import _classify

    return _classify(factor, tolerance)


def traffic_light(status: str, factor: Decimal | None, tolerance: Decimal = DEFAULT_TOLERANCE) -> str:
    """Green within tolerance or faster, amber up to three tolerances slower, red beyond.

    Hours booked with nothing installed are red: that is the case a foreman
    has to chase today. No norm or nothing booked yet is grey, never green.
    """
    if status == "no_progress":
        return LIGHT_RED
    if factor is None:
        return LIGHT_GREY
    if factor <= _ONE + tolerance:
        return LIGHT_GREEN
    if factor <= _ONE + tolerance * _AMBER_MULTIPLE:
        return LIGHT_AMBER
    return LIGHT_RED


@dataclass
class PositionInput:
    """One bill position as the compute needs it."""

    position_id: str
    ref: str
    description: str
    unit: str
    planned_quantity: Decimal
    norm_labour_per_unit: Decimal | None
    norm_plant_per_unit: Decimal | None


@dataclass
class Booking:
    """One counted timesheet line, already resolved to a position where possible."""

    day: date
    hours: Decimal
    kind: str  # "labour" | "plant"
    position_id: str | None = None
    cost_code: str = ""
    worker_id: str | None = None
    crew_id: str | None = None
    crew_name: str = ""


@dataclass
class QuantityInput:
    """Installed quantity of one position: per week of the period plus cumulative to date."""

    source: str  # "measurement" | "progress"
    weekly: dict[date, Decimal] = field(default_factory=dict)
    to_date: Decimal = _ZERO


def _factor(spent: Decimal, earned: Decimal) -> Decimal | None:
    return spent / earned if earned > 0 and spent > 0 else None


def _status(labour: Decimal, qty: Decimal, earned: Decimal | None, tolerance: Decimal) -> str:
    if earned is None:
        return "no_baseline" if (labour > 0 or qty > 0) else "no_actuals"
    if labour <= 0 and qty <= 0:
        return "no_actuals"
    if labour > 0 and qty <= 0:
        return "no_progress"
    if labour <= 0:
        return "no_actuals"
    return classify(labour / earned, tolerance) if earned > 0 else "no_baseline"


def compute_productivity(
    positions: Sequence[PositionInput],
    bookings: Iterable[Booking],
    quantities: Mapping[str, QuantityInput],
    *,
    date_from: date,
    date_to: date,
    hours_to_date: Mapping[str, Decimal] | None = None,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Build the foreman productivity report for one period.

    Args:
        positions: Every bill position of the project.
        bookings: Counted labour and plant lines inside the period.
        quantities: Installed quantity per position id.
        date_from: First day of the period.
        date_to: Last day of the period.
        hours_to_date: Labour hours per position from the first booking up to
            ``date_to``; the forecast rate. Falls back to the period rate.
        tolerance: On-plan band around a factor of 1.

    Returns:
        A JSON-ready dict: ``rows`` (one per position with hours or quantity,
        plus one per unresolved cost code), ``totals`` and ``weeks``.
    """
    weeks = period_weeks(date_from, date_to)
    by_pos: dict[str, list[Booking]] = {}
    unresolved: dict[str, list[Booking]] = {}
    for b in bookings:
        if b.position_id:
            by_pos.setdefault(b.position_id, []).append(b)
        else:
            unresolved.setdefault(b.cost_code or "", []).append(b)

    hours_to_date = hours_to_date or {}
    rows: list[dict[str, Any]] = []
    tot_labour = tot_plant = tot_earned = tot_earned_spent = _ZERO
    week_tot: dict[date, dict[str, Decimal]] = {w: {"labour": _ZERO, "earned": _ZERO, "spent": _ZERO} for w in weeks}

    for pos in positions:
        books = by_pos.get(pos.position_id, [])
        qin = quantities.get(pos.position_id)
        qty = sum((v for w, v in (qin.weekly.items() if qin else []) if w in week_tot), _ZERO)
        labour = sum((b.hours for b in books if b.kind == "labour"), _ZERO)
        plant = sum((b.hours for b in books if b.kind == "plant"), _ZERO)
        if not books and qty == 0:
            continue
        norm = pos.norm_labour_per_unit if pos.norm_labour_per_unit and pos.norm_labour_per_unit > 0 else None
        earned = qty * norm if norm is not None else None
        factor = _factor(labour, earned) if earned is not None else None
        status = _status(labour, qty, earned, tolerance)
        if earned is not None and labour > 0 and earned > 0:
            tot_earned += earned
            tot_earned_spent += labour
        tot_labour += labour
        tot_plant += plant

        week_rows = []
        for w in weeks:
            wl = sum((b.hours for b in books if b.kind == "labour" and week_start(b.day) == w), _ZERO)
            wq = qin.weekly.get(w, _ZERO) if qin else _ZERO
            we = wq * norm if norm is not None else None
            if we is not None and wl > 0 and we > 0:
                week_tot[w]["earned"] += we
                week_tot[w]["spent"] += wl
            week_tot[w]["labour"] += wl
            week_rows.append(
                {
                    "week_start": w.isoformat(),
                    "labour_hours": _s(wl, _HOURS_Q),
                    "quantity": _s(wq, _QTY_Q),
                    "productivity_factor": _s(_factor(wl, we) if we is not None else None, _FACTOR_Q),
                }
            )

        installed_to_date = qin.to_date if qin else _ZERO
        remaining = max(pos.planned_quantity - installed_to_date, _ZERO)
        cum_hours = hours_to_date.get(pos.position_id, _ZERO)
        if cum_hours > 0 and installed_to_date > 0:
            rate, basis = cum_hours / installed_to_date, "to_date_rate"
        elif labour > 0 and qty > 0:
            rate, basis = labour / qty, "period_rate"
        elif norm is not None:
            rate, basis = norm, "norm"
        else:
            rate, basis = None, "none"

        rows.append(
            {
                "position_id": pos.position_id,
                "cost_code": pos.ref,
                "ref": pos.ref,
                "description": pos.description,
                "unit": pos.unit,
                "planned_quantity": _s(pos.planned_quantity, _QTY_Q),
                "installed_quantity": _s(qty, _QTY_Q),
                "installed_to_date": _s(installed_to_date, _QTY_Q),
                "quantity_source": qin.source if qin else None,
                "labour_hours": _s(labour, _HOURS_Q),
                "plant_hours": _s(plant, _HOURS_Q),
                "norm_labour_hours_per_unit": _s(norm, _QTY_Q),
                "norm_plant_hours_per_unit": _s(pos.norm_plant_per_unit, _QTY_Q),
                "actual_hours_per_unit": _s(labour / qty if qty > 0 and labour > 0 else None, _QTY_Q),
                "units_per_man_hour": _s(qty / labour if qty > 0 and labour > 0 else None, _QTY_Q),
                "earned_hours": _s(earned, _HOURS_Q),
                "productivity_factor": _s(factor, _FACTOR_Q),
                "status": status,
                "light": traffic_light(status, factor, tolerance),
                "remaining_quantity": _s(remaining, _QTY_Q),
                "budget_hours_to_complete": _s(remaining * norm if norm is not None else None, _HOURS_Q),
                "forecast_hours_to_complete": _s(remaining * rate if rate is not None else None, _HOURS_Q),
                "forecast_basis": basis,
                "weeks": week_rows,
                "crews": _crews(books),
            }
        )

    for code, books in sorted(unresolved.items()):
        labour = sum((b.hours for b in books if b.kind == "labour"), _ZERO)
        plant = sum((b.hours for b in books if b.kind == "plant"), _ZERO)
        tot_labour += labour
        tot_plant += plant
        rows.append(
            {
                "position_id": None,
                "cost_code": code,
                "ref": code,
                "description": "",
                "unit": "",
                "planned_quantity": None,
                "installed_quantity": None,
                "installed_to_date": None,
                "quantity_source": None,
                "labour_hours": _s(labour, _HOURS_Q),
                "plant_hours": _s(plant, _HOURS_Q),
                "norm_labour_hours_per_unit": None,
                "norm_plant_hours_per_unit": None,
                "actual_hours_per_unit": None,
                "units_per_man_hour": None,
                "earned_hours": None,
                "productivity_factor": None,
                "status": "no_baseline",
                "light": LIGHT_GREY,
                "remaining_quantity": None,
                "budget_hours_to_complete": None,
                "forecast_hours_to_complete": None,
                "forecast_basis": "none",
                "weeks": [],
                "crews": _crews(books),
            }
        )

    # Worst first: red, amber, grey, green; then the most hours.
    order = {LIGHT_RED: 0, LIGHT_AMBER: 1, LIGHT_GREY: 2, LIGHT_GREEN: 3}
    rows.sort(key=lambda r: (order.get(r["light"], 9), -_dec(r["labour_hours"])))

    tot_factor = _factor(tot_earned_spent, tot_earned)
    tot_status = classify(tot_factor, tolerance) if tot_factor is not None else "no_baseline"
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "tolerance": str(tolerance),
        "rows": rows,
        "totals": {
            "labour_hours": _s(tot_labour, _HOURS_Q),
            "plant_hours": _s(tot_plant, _HOURS_Q),
            "earned_hours": _s(tot_earned, _HOURS_Q),
            "spent_hours_with_norm": _s(tot_earned_spent, _HOURS_Q),
            "productivity_factor": _s(tot_factor, _FACTOR_Q),
            "status": tot_status,
            "light": traffic_light(tot_status, tot_factor, tolerance),
        },
        "weeks": [
            {
                "week_start": w.isoformat(),
                "labour_hours": _s(v["labour"], _HOURS_Q),
                "earned_hours": _s(v["earned"], _HOURS_Q),
                "productivity_factor": _s(_factor(v["spent"], v["earned"]), _FACTOR_Q),
            }
            for w, v in week_tot.items()
        ],
    }


def _crews(books: Sequence[Booking]) -> list[dict[str, Any]]:
    """Labour hours per crew on one row; a worker in no crew is grouped under ``None``."""
    labour = [b for b in books if b.kind == "labour"]
    total = sum((b.hours for b in labour), _ZERO)
    groups: dict[str | None, dict[str, Any]] = {}
    for b in labour:
        g = groups.setdefault(b.crew_id, {"name": b.crew_name, "hours": _ZERO, "workers": set()})
        g["hours"] += b.hours
        if b.worker_id:
            g["workers"].add(b.worker_id)
    out = [
        {
            "crew_id": cid,
            "crew_name": g["name"],
            "labour_hours": _s(g["hours"], _HOURS_Q),
            "share_pct": _s(g["hours"] * 100 / total if total > 0 else _ZERO, _HOURS_Q),
            "workers": len(g["workers"]),
        }
        for cid, g in groups.items()
    ]
    out.sort(key=lambda c: -_dec(c["labour_hours"]))
    return out


def quantity_from_measurements(
    entries: Iterable[tuple[date, Decimal]], date_from: date, date_to: date
) -> QuantityInput:
    """Weekly and to-date quantity from measurement book entries up to ``date_to``."""
    q = QuantityInput(source="measurement")
    for day, qty in entries:
        if day > date_to:
            continue
        q.to_date += qty
        if day >= date_from:
            w = week_start(day)
            q.weekly[w] = q.weekly.get(w, _ZERO) + qty
    return q


def quantity_from_progress(
    readings: Sequence[tuple[int, date, Decimal]],
    planned: Decimal,
    date_from: date,
    date_to: date,
) -> QuantityInput:
    """Weekly and to-date quantity from cumulative percent readings ``(seq, day, pct)``.

    The reading that counts at a cut-off is the one with the highest ``seq``
    on or before it, the progress module's own "latest wins" order. A week's
    quantity is the change of that reading across the week, clipped to the
    period, so a correction downward shows as a negative week rather than
    vanishing.
    """

    def pct_at(cutoff: date) -> Decimal:
        best: tuple[int, Decimal] | None = None
        for seq, day, pct in readings:
            if day <= cutoff and (best is None or seq > best[0]):
                best = (seq, pct)
        return best[1] if best else _ZERO

    q = QuantityInput(source="progress")
    for w in period_weeks(date_from, date_to):
        lo = max(w, date_from) - timedelta(days=1)
        hi = min(w + timedelta(days=6), date_to)
        delta = (pct_at(hi) - pct_at(lo)) * planned / 100
        if delta != 0:
            q.weekly[w] = delta
    q.to_date = pct_at(date_to) * planned / 100
    return q


class ProductivityService:
    """Loads the inputs of :func:`compute_productivity` for one project and period."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def report(
        self,
        project_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        tolerance: Decimal = DEFAULT_TOLERANCE,
        locale: str = "en",
    ) -> dict[str, Any]:
        """Productivity rows, totals and validation findings for the period."""
        positions = await self._positions(project_id)
        code_to_pid, wbs_to_pid = _position_keys(positions)
        bookings_all = await self._bookings(project_id, date_to, code_to_pid, wbs_to_pid)
        period = [b for b in bookings_all if b.day >= date_from]
        hours_to_date: dict[str, Decimal] = {}
        for b in bookings_all:
            if b.kind == "labour" and b.position_id:
                hours_to_date[b.position_id] = hours_to_date.get(b.position_id, _ZERO) + b.hours
        inputs = [_position_input(p) for p in positions]
        planned = {p.position_id: p.planned_quantity for p in inputs}
        quantities = await self._quantities(project_id, planned, date_from, date_to)
        out = compute_productivity(
            inputs,
            period,
            quantities,
            date_from=date_from,
            date_to=date_to,
            hours_to_date=hours_to_date,
            tolerance=tolerance,
        )
        out["project_id"] = str(project_id)
        out["findings"] = await self._findings(project_id, out, locale)
        return out

    async def _positions(self, project_id: uuid.UUID) -> list[Any]:
        try:
            from app.modules.boq.repository import PositionRepository

            return list(await PositionRepository(self.session).list_for_project(project_id))
        except Exception:
            logger.debug("BOQ positions unavailable for %s", project_id, exc_info=True)
            return []

    async def _bookings(
        self,
        project_id: uuid.UUID,
        date_to: date,
        code_to_pid: dict[str, str],
        wbs_to_pid: dict[str, str],
    ) -> list[Booking]:
        from app.modules.field_time.counted import counted_timesheet_clause
        from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine

        stmt = (
            select(
                FieldTimesheet.date,
                FieldTimesheetLine.hours,
                FieldTimesheetLine.resource_id,
                FieldTimesheetLine.equipment_id,
                FieldTimesheetLine.boq_position_id,
                FieldTimesheetLine.cost_code,
                FieldTimesheetLine.wbs,
            )
            .join(FieldTimesheet, FieldTimesheetLine.timesheet_id == FieldTimesheet.id)
            .where(FieldTimesheet.project_id == project_id, FieldTimesheet.date <= date_to, counted_timesheet_clause())
        )
        rows = (await self.session.execute(stmt)).all()
        known = set(code_to_pid.values())
        crew_of = await self._crews_of({r[2] for r in rows if r[2] is not None})
        out: list[Booking] = []
        for day, hours, rid, eid, bpid, code, wbs in rows:
            pid = str(bpid) if bpid is not None and str(bpid) in known else None
            code = str(code or "").strip()
            if pid is None:
                pid = code_to_pid.get(code) or wbs_to_pid.get(str(wbs or "").strip())
            crew = crew_of.get(rid) if rid is not None else None
            out.append(
                Booking(
                    day=day,
                    hours=_dec(hours),
                    kind="labour" if rid is not None else "plant",
                    position_id=pid,
                    cost_code=code,
                    worker_id=str(rid) if rid is not None else (str(eid) if eid is not None else None),
                    crew_id=crew[0] if crew else None,
                    crew_name=crew[1] if crew else "",
                )
            )
        return out

    async def _crews_of(self, worker_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
        """``{worker id: (crew id, crew name)}`` from the resources crew links."""
        if not worker_ids:
            return {}
        try:
            from app.modules.resources.models import Resource, ResourceLink

            stmt = (
                select(ResourceLink.secondary_resource_id, Resource.id, Resource.name)
                .join(Resource, Resource.id == ResourceLink.primary_resource_id)
                .where(
                    ResourceLink.link_type == "crew_member",
                    ResourceLink.secondary_resource_id.in_(list(worker_ids)),
                )
            )
            rows = (await self.session.execute(stmt)).all()
        except Exception:
            logger.debug("Crew links unavailable", exc_info=True)
            return {}
        out: dict[uuid.UUID, tuple[str, str]] = {}
        for member, crew_id, name in rows:
            out.setdefault(member, (str(crew_id), name or ""))
        return out

    async def _quantities(
        self,
        project_id: uuid.UUID,
        planned: dict[str, Decimal],
        date_from: date,
        date_to: date,
    ) -> dict[str, QuantityInput]:
        ids = [uuid.UUID(pid) for pid in planned]
        if not ids:
            return {}
        measured: dict[str, list[tuple[date, Decimal]]] = {}
        try:
            from app.modules.measurement_book.models import MeasurementBookEntry as M

            stmt = select(M.boq_position_id, M.entry_date, M.quantity, M.check_quantity).where(
                M.project_id == project_id,
                M.boq_position_id.in_(ids),
                M.entry_date <= date_to,
                M.check_status != "disputed",
            )
            for pid, day, qty, check in (await self.session.execute(stmt)).all():
                measured.setdefault(str(pid), []).append((day, _dec(check if check is not None else qty)))
        except Exception:
            logger.debug("Measurement book unavailable for %s", project_id, exc_info=True)

        readings: dict[str, list[tuple[int, date, Decimal]]] = {}
        try:
            from app.modules.progress.models import ProgressEntry as P

            cutoff = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
            stmt = select(P.boq_position_id, P.seq, P.recorded_at, P.percent_complete).where(
                P.project_id == project_id, P.boq_position_id.in_(ids), P.recorded_at < cutoff
            )
            for pid, seq, rec, pct in (await self.session.execute(stmt)).all():
                day = rec.date() if isinstance(rec, datetime) else rec
                readings.setdefault(str(pid), []).append((int(seq or 0), day, _dec(pct)))
        except Exception:
            logger.debug("Progress readings unavailable for %s", project_id, exc_info=True)

        out: dict[str, QuantityInput] = {}
        for pid, qty in planned.items():
            if pid in measured:
                out[pid] = quantity_from_measurements(measured[pid], date_from, date_to)
            elif pid in readings:
                out[pid] = quantity_from_progress(readings[pid], qty, date_from, date_to)
        return out

    async def _findings(self, project_id: uuid.UUID, report: dict[str, Any], locale: str) -> list[dict[str, Any]]:
        from app.core.validation.engine import validation_engine

        result = await validation_engine.validate(
            data={
                "productivity_rows": [r for r in report["rows"] if r["position_id"]],
                "date_from": report["date_from"],
                "date_to": report["date_to"],
                "band_low": str(DEFAULT_PLAUSIBLE_LOW),
                "band_high": str(DEFAULT_PLAUSIBLE_HIGH),
            },
            rule_sets=["field_productivity"],
            target_type="field_productivity",
            target_id=str(project_id),
            project_id=str(project_id),
            metadata={"locale": locale},
        )
        return [
            {
                "rule_id": r.rule_id,
                "severity": r.severity.value if hasattr(r.severity, "value") else str(r.severity),
                "message": r.message,
                "suggestion": r.suggestion,
                "element_ref": r.element_ref,
            }
            for r in result.results
            if not r.passed
        ]


def _position_keys(positions: Sequence[Any]) -> tuple[dict[str, str], dict[str, str]]:
    """The same cost-code and WBS keys post-calculation resolves a booking with."""
    code_to_pid: dict[str, str] = {}
    wbs_to_pid: dict[str, str] = {}
    for pos in positions:
        pid = str(pos.id)
        for code in (getattr(pos, "reference_code", None), pos.ordinal, getattr(pos, "cost_code_id", None)):
            key = str(code).strip() if code else ""
            if key:
                code_to_pid.setdefault(key, pid)
        wbs = str(pos.wbs_id).strip() if getattr(pos, "wbs_id", None) else ""
        if wbs:
            wbs_to_pid.setdefault(wbs, pid)
    for pos in positions:
        code_to_pid.setdefault(str(pos.id), str(pos.id))
    return code_to_pid, wbs_to_pid


def _position_input(pos: Any) -> PositionInput:
    from app.modules.postcalc.service import _per_unit_hours, _resources_of
    from app.modules.price_breakdown import ResourceKind

    line = {"metadata_": pos.metadata_ if isinstance(pos.metadata_, dict) else {}}
    resources = _resources_of(line)
    labour = _per_unit_hours(resources, ResourceKind.LABOUR) if resources else _ZERO
    plant = _per_unit_hours(resources, ResourceKind.MACHINERY) if resources else _ZERO
    return PositionInput(
        position_id=str(pos.id),
        ref=str(getattr(pos, "reference_code", None) or pos.ordinal or "").strip(),
        description=pos.description or "",
        unit=pos.unit or "",
        planned_quantity=_dec(pos.quantity),
        norm_labour_per_unit=labour if labour > 0 else None,
        norm_plant_per_unit=plant if plant > 0 else None,
    )


__all__ = [
    "DEFAULT_PLAUSIBLE_HIGH",
    "DEFAULT_PLAUSIBLE_LOW",
    "DEFAULT_TOLERANCE",
    "MAX_PERIOD_DAYS",
    "Booking",
    "PositionInput",
    "ProductivityService",
    "QuantityInput",
    "compute_productivity",
    "quantity_from_measurements",
    "quantity_from_progress",
    "traffic_light",
]
