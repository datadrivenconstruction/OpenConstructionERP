# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Workforce demand by trade against the people, crews and subcontractors available.

The capacity heatmap answers "is this named person double booked". A resource
planner also needs the question before anybody is named: across every project,
how many carpenters does the programme need in week 14, how many do we have,
and which activities make the peak.

Demand, in full-time equivalents per ISO week:

* schedule activities: each labour entry of ``Activity.resources``. An entry
  carrying man-hours (``hours`` / ``man_hours`` / ``units`` / ``quantity``) is
  spread evenly over the activity's working days and scaled by the share still
  to do (``1 - progress_pct``); an entry carrying a head count (``headcount``
  / ``crew_size`` / ``count``, else ``allocation_pct / 100``) loads that many
  people for every working day it overlaps. Its trade is ``trade`` / ``role``
  / ``skill`` / ``craft``.
* staffing positions that are not cancelled: ``fte * headcount`` between entry
  and exit date, under the position's role code.

Availability: active people at their declared capacity, less unavailable,
holiday and sick windows, split evenly over their trade skills; crews only
when they have no member links (members are already counted as people) at
their ``crew_size`` / ``headcount``; subcontractors at their declared
``headcount``. A subcontractor with no declared head count adds nothing and
is counted in ``capacity_unknown`` instead of being guessed.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_FTE_Q = Decimal("0.01")
HOURS_PER_FTE_WEEK = Decimal("40")
MAX_WEEKS = 52
#: Contributors listed per cell for the drill-down; the rest are summed.
MAX_CONTRIBUTORS = 8

LABOUR_TYPES = frozenset({"labor", "labour", "person", "crew", "worker", "manpower", "staff"})
_TRADE_KEYS = ("trade", "role", "skill", "craft")
_HOURS_KEYS = ("hours", "man_hours", "units", "quantity")
_HEAD_KEYS = ("headcount", "crew_size", "count")
_UNAVAILABLE = frozenset({"unavailable", "holiday", "sick"})
UNASSIGNED = ""


def _dec(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value if value.is_finite() else _ZERO
    if value is None or value == "" or isinstance(value, bool):
        return _ZERO
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO
    return out if out.is_finite() else _ZERO


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or len(value.strip()) < 10:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def working_days(start: date, end: date) -> int:
    """Monday to Friday days in ``[start, end]``; zero when the range is empty."""
    if end < start:
        return 0
    days = (end - start).days + 1
    full, rest = divmod(days, 7)
    count = full * 5
    for i in range(rest):
        if (start + timedelta(days=full * 7 + i)).weekday() < 5:
            count += 1
    return count


def build_weeks(start: date, count: int) -> list[tuple[date, date]]:
    """``count`` ISO weeks from the Monday of ``start``, each as (Monday, Sunday)."""
    monday = start - timedelta(days=start.weekday())
    return [(monday + timedelta(days=7 * i), monday + timedelta(days=7 * i + 6)) for i in range(count)]


class TradeCatalog:
    """Maps free-text trades onto trade skill codes so "Carpentry" and "trade.carpentry" meet."""

    def __init__(self, skills: Iterable[tuple[str, str]] = ()) -> None:
        self._by_key: dict[str, str] = {}
        self.labels: dict[str, str] = {}
        for code, name in skills:
            c = code.strip().lower()
            self.labels[c] = name or code
            self._by_key[c] = c
            if name:
                self._by_key[name.strip().lower()] = c
            if c.startswith("trade."):
                self._by_key[c[6:]] = c

    def key(self, raw: object) -> str:
        """The trade key for a raw value; ``UNASSIGNED`` when blank."""
        text = str(raw or "").strip()
        if not text:
            return UNASSIGNED
        low = text.lower()
        hit = self._by_key.get(low) or self._by_key.get(f"trade.{low}")
        if hit:
            return hit
        self.labels.setdefault(low, text)
        return low


@dataclass
class DemandItem:
    """One activity labour entry or staffing position, before it is spread over weeks."""

    kind: str  # "activity" | "staffing"
    source_id: str
    name: str
    project_id: str | None
    project_name: str
    trade: str
    start: date
    end: date
    man_hours: Decimal | None = None
    headcount: Decimal | None = None


@dataclass
class SupplyItem:
    """One person, crew or subcontractor's capacity for one trade."""

    resource_id: str
    resource_type: str
    trades: list[str]
    heads: Decimal
    unavailable: list[tuple[date, date]] = field(default_factory=list)


def activity_demand(
    activity: Any, project_id: str | None, project_name: str, catalog: TradeCatalog
) -> tuple[list[DemandItem], list[dict[str, Any]]]:
    """Demand items of one activity plus the labour entries the trade rule reads."""
    start = _as_date(getattr(activity, "start_date", None))
    end = _as_date(getattr(activity, "end_date", None))
    status = str(getattr(activity, "status", "") or "").lower()
    progress = _dec(getattr(activity, "progress_pct", None))
    if start is None or end is None or end < start or status == "completed" or progress >= 100:
        return [], []
    remaining = (Decimal("100") - max(progress, _ZERO)) / 100
    items: list[DemandItem] = []
    checks: list[dict[str, Any]] = []
    for res in getattr(activity, "resources", None) or []:
        if not isinstance(res, dict):
            continue
        if str(res.get("type") or "").strip().lower() not in LABOUR_TYPES:
            continue
        raw_trade = next((res.get(k) for k in _TRADE_KEYS if res.get(k)), None)
        trade = catalog.key(raw_trade)
        hours = next((_dec(res.get(k)) for k in _HOURS_KEYS if _dec(res.get(k)) > 0), None)
        heads = next((_dec(res.get(k)) for k in _HEAD_KEYS if _dec(res.get(k)) > 0), None)
        if hours is None and heads is None:
            pct = _dec(res.get("allocation_pct", 100))
            heads = pct / 100 if pct > 0 else None
        if hours is None and heads is None:
            continue
        item = DemandItem(
            kind="activity",
            source_id=str(getattr(activity, "id", "")),
            name=str(getattr(activity, "name", "") or ""),
            project_id=project_id,
            project_name=project_name,
            trade=trade,
            start=start,
            end=end,
            man_hours=hours * remaining if hours is not None else None,
            headcount=heads if hours is None else None,
        )
        items.append(item)
        checks.append(
            {
                "activity_id": item.source_id,
                "name": item.name,
                "project_name": project_name,
                "trade": trade,
                "man_hours": str(hours) if hours is not None else None,
                "fte": str(heads) if heads is not None else None,
            }
        )
    return items, checks


def _week_fte(item: DemandItem, w_start: date, w_end: date) -> Decimal:
    lo, hi = max(item.start, w_start), min(item.end, w_end)
    overlap = working_days(lo, hi)
    if overlap <= 0:
        return _ZERO
    if item.man_hours is not None:
        total = max(working_days(item.start, item.end), 1)
        return item.man_hours * overlap / total / HOURS_PER_FTE_WEEK
    return (item.headcount or _ZERO) * overlap / 5


def _supply_fte(item: SupplyItem, w_start: date, w_end: date) -> Decimal:
    days = working_days(w_start, w_end)
    if days <= 0 or not item.trades:
        return _ZERO
    off = 0
    for lo, hi in item.unavailable:
        off += working_days(max(lo, w_start), min(hi, w_end))
    free = max(days - off, 0)
    return item.heads * free / days / len(item.trades)


def cell_status(demand: Decimal, available: Decimal) -> str:
    """``short`` / ``tight`` / ``balanced`` / ``surplus`` / ``idle`` for one trade-week."""
    if demand <= 0 and available <= 0:
        return "idle"
    if demand > available + Decimal("0.05"):
        return "short"
    if demand >= available * Decimal("0.9"):
        return "tight"
    if available - demand >= 1 and available > demand * Decimal("1.25"):
        return "surplus"
    return "balanced"


def compute_workforce(
    demand: Sequence[DemandItem],
    supply: Sequence[SupplyItem],
    weeks: Sequence[tuple[date, date]],
    labels: Mapping[str, str],
) -> dict[str, Any]:
    """Trade x week grid of demand, availability and gap, worst trades first."""
    trades: dict[str, dict[str, Any]] = {}

    def slot(trade: str) -> dict[str, Any]:
        return trades.setdefault(
            trade,
            {
                "demand": [_ZERO] * len(weeks),
                "available": [_ZERO] * len(weeks),
                "contrib": [[] for _ in weeks],
                "heads": set(),
            },
        )

    for item in demand:
        s = slot(item.trade)
        for i, (ws, we) in enumerate(weeks):
            fte = _week_fte(item, ws, we)
            if fte > 0:
                s["demand"][i] += fte
                s["contrib"][i].append((fte, item))
    for sup in supply:
        for trade in sup.trades:
            s = slot(trade)
            s["heads"].add(sup.resource_id)
            for i, (ws, we) in enumerate(weeks):
                s["available"][i] += _supply_fte(sup, ws, we)

    rows: list[dict[str, Any]] = []
    for trade, s in trades.items():
        cells = []
        peak_demand = peak_short = _ZERO
        short_weeks = 0
        for i in range(len(weeks)):
            d, a = s["demand"][i], s["available"][i]
            gap = a - d
            status = cell_status(d, a)
            if status == "short":
                short_weeks += 1
            peak_demand = max(peak_demand, d)
            peak_short = max(peak_short, -gap)
            contrib = sorted(s["contrib"][i], key=lambda c: -c[0])
            cells.append(
                {
                    "week_index": i,
                    "demand_fte": str(d.quantize(_FTE_Q)),
                    "available_fte": str(a.quantize(_FTE_Q)),
                    "gap_fte": str(gap.quantize(_FTE_Q)),
                    "status": status,
                    "contributors": [
                        {
                            "kind": it.kind,
                            "id": it.source_id,
                            "name": it.name,
                            "project_id": it.project_id,
                            "project_name": it.project_name,
                            "fte": str(fte.quantize(_FTE_Q)),
                            "start": it.start.isoformat(),
                            "end": it.end.isoformat(),
                        }
                        for fte, it in contrib[:MAX_CONTRIBUTORS]
                    ],
                    "more_contributors": max(len(contrib) - MAX_CONTRIBUTORS, 0),
                }
            )
        rows.append(
            {
                "trade": trade,
                "label": labels.get(trade, trade) if trade else "",
                "unassigned": trade == UNASSIGNED,
                "available_resources": len(s["heads"]),
                "peak_demand_fte": str(peak_demand.quantize(_FTE_Q)),
                "peak_shortfall_fte": str(max(peak_short, _ZERO).quantize(_FTE_Q)),
                "short_weeks": short_weeks,
                "cells": cells,
            }
        )
    rows.sort(key=lambda r: (-Decimal(r["peak_shortfall_fte"]), -r["short_weeks"], r["label"].lower()))
    return {
        "weeks": [
            {"index": i, "start": ws.isoformat(), "end": we.isoformat(), "label": f"W{ws.isocalendar()[1]:02d}"}
            for i, (ws, we) in enumerate(weeks)
        ],
        "hours_per_fte_week": str(HOURS_PER_FTE_WEEK),
        "trades": rows,
        "short_trades": sum(1 for r in rows if r["short_weeks"] > 0),
    }


class WorkforceDemandService:
    """Loads demand and supply across every project and builds the trade grid."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def forecast(self, start: date, weeks: int = 12, *, locale: str = "en") -> dict[str, Any]:
        """Trade demand vs availability for ``weeks`` ISO weeks from ``start``."""
        weeks = max(1, min(weeks, MAX_WEEKS))
        grid = build_weeks(start, weeks)
        w_start, w_end = grid[0][0], grid[-1][1]
        catalog = TradeCatalog(await self._trade_skills())
        demand, checks = await self._activity_demand(w_start, w_end, catalog)
        demand += await self._staffing_demand(w_start, w_end, catalog)
        supply, unknown = await self._supply(w_start, w_end, catalog)
        out = compute_workforce(demand, supply, grid, catalog.labels)
        out["start"] = w_start.isoformat()
        out["end"] = w_end.isoformat()
        out["capacity_unknown"] = unknown
        out["findings"] = await self._findings(checks, locale)
        return out

    async def _trade_skills(self) -> list[tuple[str, str]]:
        from app.modules.resources.models import Skill

        rows = (await self.session.execute(select(Skill.code, Skill.name).where(Skill.category == "trade"))).all()
        return [(c, n) for c, n in rows]

    async def _project_names(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        from app.modules.projects.models import Project

        rows = (await self.session.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all()
        return {pid: name for pid, name in rows}

    async def _activity_demand(
        self, w_start: date, w_end: date, catalog: TradeCatalog
    ) -> tuple[list[DemandItem], list[dict[str, Any]]]:
        try:
            from app.modules.schedule.models import Activity, Schedule
        except Exception:
            logger.debug("Schedule module unavailable", exc_info=True)
            return [], []
        stmt = (
            select(Activity, Schedule.project_id)
            .join(Schedule, Schedule.id == Activity.schedule_id)
            .where(Activity.start_date <= w_end.isoformat() + "T99", Activity.end_date >= w_start.isoformat())
        )
        rows = (await self.session.execute(stmt)).all()
        names = await self._project_names({pid for _, pid in rows if pid is not None})
        items: list[DemandItem] = []
        checks: list[dict[str, Any]] = []
        for act, pid in rows:
            got, chk = activity_demand(act, str(pid) if pid else None, names.get(pid, ""), catalog)
            items += got
            checks += chk
        return items, checks

    async def _staffing_demand(self, w_start: date, w_end: date, catalog: TradeCatalog) -> list[DemandItem]:
        try:
            from app.modules.staffing.models import StaffingPosition as S
        except Exception:
            logger.debug("Staffing module unavailable", exc_info=True)
            return []
        stmt = select(S).where(S.status != "cancelled")
        positions = list((await self.session.execute(stmt)).scalars().all())
        names = await self._project_names({p.project_id for p in positions})
        out: list[DemandItem] = []
        for p in positions:
            start = p.entry_date or w_start
            end = p.exit_date or w_end
            if end < w_start or start > w_end or end < start:
                continue
            heads = _dec(p.fte) * Decimal(max(int(p.headcount or 0), 0))
            if heads <= 0:
                continue
            out.append(
                DemandItem(
                    kind="staffing",
                    source_id=str(p.id),
                    name=p.title or p.custom_label or p.role_code,
                    project_id=str(p.project_id),
                    project_name=names.get(p.project_id, ""),
                    trade=catalog.key(p.role_code),
                    start=start,
                    end=end,
                    headcount=heads,
                )
            )
        return out

    async def _supply(self, w_start: date, w_end: date, catalog: TradeCatalog) -> tuple[list[SupplyItem], int]:
        from app.modules.resources.models import AvailabilityWindow, Resource, ResourceLink, ResourceSkill, Skill

        resources = list(
            (
                await self.session.execute(
                    select(Resource).where(
                        Resource.status == "active",
                        Resource.resource_type.in_(("person", "crew", "subcontractor")),
                    )
                )
            )
            .scalars()
            .all()
        )
        ids = [r.id for r in resources]
        if not ids:
            return [], 0
        skill_rows = (
            await self.session.execute(
                select(ResourceSkill.resource_id, Skill.code)
                .join(Skill, Skill.id == ResourceSkill.skill_id)
                .where(Skill.category == "trade", ResourceSkill.resource_id.in_(ids))
            )
        ).all()
        trades: dict[uuid.UUID, list[str]] = {}
        for rid, code in skill_rows:
            trades.setdefault(rid, []).append(catalog.key(code))
        crews_with_members = {
            row[0]
            for row in (
                await self.session.execute(
                    select(ResourceLink.primary_resource_id).where(
                        ResourceLink.link_type == "crew_member", ResourceLink.primary_resource_id.in_(ids)
                    )
                )
            ).all()
        }
        lo = datetime.combine(w_start, datetime.min.time(), tzinfo=UTC)
        hi = datetime.combine(w_end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        windows: dict[uuid.UUID, list[tuple[date, date]]] = {}
        for rid, wtype, s, e in (
            await self.session.execute(
                select(
                    AvailabilityWindow.resource_id,
                    AvailabilityWindow.window_type,
                    AvailabilityWindow.start_at,
                    AvailabilityWindow.end_at,
                ).where(
                    AvailabilityWindow.resource_id.in_(ids),
                    AvailabilityWindow.start_at < hi,
                    AvailabilityWindow.end_at > lo,
                )
            )
        ).all():
            if wtype in _UNAVAILABLE:
                windows.setdefault(rid, []).append((s.date(), (e - timedelta(microseconds=1)).date()))

        out: list[SupplyItem] = []
        unknown = 0
        for r in resources:
            meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
            if r.resource_type == "person":
                heads = Decimal(r.capacity_percent if r.capacity_percent is not None else 100) / 100
            elif r.resource_type == "crew":
                if r.id in crews_with_members:
                    continue
                heads = next((_dec(meta.get(k)) for k in ("crew_size", "headcount") if _dec(meta.get(k)) > 0), None)
                heads = heads if heads is not None else Decimal("1")
            else:
                heads = next(
                    (_dec(meta.get(k)) for k in ("headcount", "capacity_headcount") if _dec(meta.get(k)) > 0),
                    None,
                )
                if heads is None:
                    unknown += 1
                    continue
            own = trades.get(r.id) or ([catalog.key(meta.get("trade"))] if meta.get("trade") else [UNASSIGNED])
            out.append(SupplyItem(str(r.id), r.resource_type, own, heads, windows.get(r.id, [])))
        return out, unknown

    async def _findings(self, checks: list[dict[str, Any]], locale: str) -> list[dict[str, Any]]:
        from app.core.validation.engine import validation_engine

        report = await validation_engine.validate(
            data={"workforce_activities": checks},
            rule_sets=["workforce"],
            target_type="workforce_demand",
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
            for r in report.results
            if not r.passed
        ]


__all__ = [
    "HOURS_PER_FTE_WEEK",
    "MAX_WEEKS",
    "DemandItem",
    "SupplyItem",
    "TradeCatalog",
    "WorkforceDemandService",
    "activity_demand",
    "build_weeks",
    "cell_status",
    "compute_workforce",
    "working_days",
]
