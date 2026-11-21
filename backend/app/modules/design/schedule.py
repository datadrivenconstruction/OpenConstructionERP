"""Schedule from model revisions (R10), written into the ERP's own schedule module.

One activity per estimate rule and storey (``per_storey`` rules) or per building, linked to the rule's estimate
position through ``boq_position_ids``. A duration is derived, never typed: ``ceil(quantity × labour hours per unit ÷
(crew × hours per day))`` with the labour value from a sourced rates file (``data/schedule``). A rule without a
sourced value gets no activity and is flagged ``rate_missing``. Links follow the file's ``logic`` block (an
assumption, said so). Dates come from the ERP's CPM engine.

A duration a person changed in the schedule (differs from what this module last wrote and from what the rates give
now) is an override: kept, flagged, the model value stored beside it. Activities are never deleted.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.json_merge import merge_metadata

from . import estimate as est_mod
from .models import DesignEstimate, DesignRevision, DesignSchedule, DesignScheduleBinding

SCHEMA = "ddc-schedule-rates/1"
IMPACT_SCHEMA = "ddc-schedule-impact/1"
DATA = Path(__file__).resolve().parent / "data" / "schedule"
FORMULA = "ceil(quantity × labour_h_per_unit ÷ (crew × hours_per_day))"
LOGIC_NOTE = "The order of trades and the storey-by-storey sequence are a planning assumption, not sourced data."
SCHEDULE_URL = "/schedule"


class RatesError(ValueError):
    pass


# ── rates files ─────────────────────────────────────────────────────────────


def _is_date(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    try:
        if len(v) == 4:
            return v.isdigit()
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def _rate_value(r: dict[str, Any]) -> Decimal:
    if "value" in r:
        return Decimal(str(r["value"]))
    return Decimal(str(r[r["use"]]))


def validate_rates(doc: dict[str, Any]) -> dict[str, Any]:
    """Every number names its source, page, dates and the quote it was read in; otherwise it must be absent."""
    if doc.get("schema") != SCHEMA:
        raise RatesError(f"schema must be {SCHEMA}")
    for k in ("country", "use"):
        if not isinstance(doc.get(k), str) or not doc[k]:
            raise RatesError(f"{k} is required")
    rates, logic = doc.get("rates"), doc.get("logic")
    if not isinstance(rates, dict) or not isinstance(logic, dict):
        raise RatesError("rates and logic must be objects")
    for code, entry in rates.items():
        if "not_scheduled" in entry:
            if not str(entry["not_scheduled"]).strip():
                raise RatesError(f"{code}: not_scheduled needs a reason")
            continue
        r = entry.get("labour_h_per_unit", "absent")
        if r == "absent":
            raise RatesError(f"{code}: labour_h_per_unit is required (null when no source exists)")
        if r is None:
            if not str(entry.get("missing") or "").strip():
                raise RatesError(f"{code}: a missing rate needs a reason")
            continue
        if "value" in r:
            nums = [r["value"]]
        else:
            if r.get("use") not in ("low", "high"):
                raise RatesError(f"{code}: a range needs use = low | high")
            nums = [r.get("low"), r.get("high")]
            if not all(isinstance(n, (int, float)) for n in nums) or nums[0] > nums[1]:
                raise RatesError(f"{code}: low and high must be numbers, low <= high")
        if not all(isinstance(n, (int, float)) and n > 0 for n in nums):
            raise RatesError(f"{code}: rate values must be positive numbers")
        if not str(r.get("unit") or "").startswith("h/"):
            raise RatesError(f"{code}: unit must be hours per unit (h/…)")
        crew = r.get("crew")
        if crew is not None and (not isinstance(crew, int) or not 1 <= crew <= 50):
            raise RatesError(f"{code}: crew must be a whole number of people or null")
        src = r.get("source") or {}
        if not str(src.get("url") or "").startswith("https://"):
            raise RatesError(f"{code}: source.url (https) is required")
        for k in ("title", "publisher", "country", "page", "quote"):
            if not str(src.get(k) or "").strip():
                raise RatesError(f"{code}: source.{k} is required")
        if not (_is_date(src.get("published")) and _is_date(src.get("retrieved"))):
            raise RatesError(f"{code}: source.published and source.retrieved must be dates")
    for code, lg in logic.items():
        if code not in rates:
            raise RatesError(f"logic names unknown rule {code}")
        for ref in [*lg.get("after", []), *lg.get("after_below", [])]:
            if ref not in rates:
                raise RatesError(f"logic of {code} names unknown rule {ref}")
        for ref in lg.get("after_below", []):
            if not (logic.get(ref) or {}).get("per_storey") or not lg.get("per_storey"):
                raise RatesError(f"{code}: after_below links two per-storey rules")
    return doc


def rates_for(country: str, use: str) -> dict[str, Any] | None:
    for f in sorted(DATA.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        if doc.get("country") == country and doc.get("use") == use:
            return validate_rates(doc)
    return None


# ── calendar and crew ───────────────────────────────────────────────────────


def calendar_for(country: str) -> dict[str, Any]:
    from app.modules.schedule.service import get_work_calendar

    cal = get_work_calendar(country)
    return {
        "hours_per_day": cal["hours_per_day"],
        "label": cal.get("label", ""),
        "week_fallback": bool(cal.get("week_fallback")),
    }


def crew_for(rate: dict[str, Any], unit: str, crews: dict[str, Any], code: str) -> tuple[int, str]:
    from app.modules.schedule.service import fallback_gang_size

    if isinstance(crews.get(code), int) and crews[code] > 0:
        return crews[code], "project_setting"
    if rate.get("crew"):
        return int(rate["crew"]), "source"
    return fallback_gang_size(unit.removeprefix("h/")), "erp_default_gang"


def duration_days(qty: Decimal, h_per_unit: Decimal, crew: int, hours_per_day: float) -> int:
    if qty <= 0:
        return 0
    days = qty * h_per_unit / (Decimal(crew) * Decimal(str(hours_per_day)))
    return max(1, int(days.to_integral_value(rounding=ROUND_CEILING)))


# ── plan ────────────────────────────────────────────────────────────────────

Slot = tuple[str, str]  # (rule code, storey); storey "" = whole building


@dataclass
class Planned:
    rule: str
    label: str
    storey: str
    quantity: Decimal
    unit: str
    duration: int | None  # None: no activity (rate missing, nothing to build)
    flags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    position_id: uuid.UUID | None = None
    preds: list[Slot] = field(default_factory=list)  # resolved to active slots

    @property
    def slot(self) -> Slot:
        return (self.rule, self.storey)

    @property
    def active(self) -> bool:
        return self.duration is not None and self.duration > 0


@dataclass
class Plan:
    slots: dict[Slot, Planned]
    order: list[Slot]  # active slots, predecessors first
    storeys: list[str]
    rate_missing: list[dict[str, Any]]
    not_scheduled: list[dict[str, Any]]
    calendar: dict[str, Any]


async def storey_order(session, model_id: uuid.UUID) -> tuple[list[str], dict[str, str]]:
    """Storeys bottom to top (lowest element bbox z, then name) and element key -> storey."""
    from app.modules.bim_hub.models import BIMElement

    low: dict[str, float | None] = {}
    of: dict[str, str] = {}
    rows = await session.execute(
        select(BIMElement.stable_id, BIMElement.storey, BIMElement.bounding_box).where(BIMElement.model_id == model_id)
    )
    for key, storey, bbox in rows:
        s = storey or ""
        of[key] = s
        z = bbox.get("min_z") if isinstance(bbox, dict) else None
        if isinstance(z, (int, float)):
            low[s] = z if low.get(s) is None else min(low[s], z)
        else:
            low.setdefault(s, None)
    order = sorted(low, key=lambda s: (s == "", low[s] is None, low[s] if low[s] is not None else 0, s))
    return order, of


async def build_plan(
    session, est: DesignEstimate, sched: DesignSchedule, rates: dict[str, Any], model_id: uuid.UUID
) -> Plan:
    rule_rows = [r for r in await est_mod._rule_rows(session, est.project_id) if r.kind != "manual"]
    bindings = await est_mod._bindings(session, est.project_id)
    computed, _ = await est_mod.evaluate(session, est, rule_rows, model_id)
    storeys, storey_of = await storey_order(session, model_id)
    cal = calendar_for(est.country)
    svc = est_mod._svc(session)
    slots: dict[Slot, Planned] = {}
    raw_preds: dict[Slot, list[Slot]] = {}
    rate_missing: list[dict[str, Any]] = []
    not_scheduled: list[dict[str, Any]] = []
    logic = rates["logic"]
    per_storey_rules = {c for c, lg in logic.items() if lg.get("per_storey")}
    by_rule: dict[str, list[Slot]] = {}

    for rule in rule_rows:
        code, body = rule.code, rule.body
        entry = rates["rates"].get(code)
        b = bindings.get(code)
        pos_id = b.position_id if b else None
        if entry is not None and "not_scheduled" in entry:
            not_scheduled.append({"rule": code, "label": body["label"], "reason": entry["not_scheduled"]})
            continue
        rate = (entry or {}).get("labour_h_per_unit")
        c = computed.get(code)
        per_storey = code in per_storey_rules and rule.kind == "model"
        if rate is None:
            rate_missing.append(
                {
                    "rule": code,
                    "label": body["label"],
                    "unit": body["unit"],
                    "missing": (entry or {}).get("missing") or "No rate entry for this rule.",
                    "quantity": est_mod.dstr(c.quantity) if c else "0",
                }
            )
        groups: dict[str, list[str]] = {}
        if rule.kind == "model" and c is not None:
            for k in c.element_keys:
                groups.setdefault(storey_of.get(k, "") if per_storey else "", []).append(k)
        if per_storey:
            targets = [s for s in storeys if s in groups]
        else:
            targets = [""] if (rule.kind != "model" or groups) else []
        # Every storey gets a slot, so links pass through a storey where this trade has nothing to do.
        all_targets = storeys if per_storey else [""]
        for s in all_targets:
            p = Planned(code, body["label"], s, Decimal(0), body["unit"], None, position_id=pos_id)
            slots[(code, s)] = p
            by_rule.setdefault(code, []).append((code, s))
            if rate is None or s not in targets:
                if rate is None:
                    p.flags.append("rate_missing")
                continue
            if rule.kind == "model":
                qfield = rate.get("quantity_field") or body["quantity"].get("field") or ""
                q = body["quantity"]
                use_formula = bool(q.get("formula")) and not rate.get("quantity_field")
                qty, _, _ = await svc._compute_link_quantity(
                    model_id=model_id,
                    stable_ids=groups[s],
                    quantity_field=qfield,
                    aggregation=q.get("aggregation", "sum"),
                    projection_mode="formula" if use_formula else "field",
                    formula=q.get("formula") if use_formula else None,
                )
                qty, unit = Decimal(str(qty)), rate["unit"].removeprefix("h/")
                n_el = len(groups[s])
            else:
                qty, unit, qfield, n_el = (c.quantity if c else Decimal(0)), body["unit"], "formula", 0
            h = _rate_value(rate)
            crew, crew_src = crew_for(rate, rate["unit"], sched.crews or {}, code)
            days = duration_days(qty, h, crew, cal["hours_per_day"])
            p.quantity, p.unit = qty, unit
            p.duration = days if days > 0 else None
            if days == 0:
                p.flags.append("no_match")
            if b is not None and "override" in (b.flags or []):
                p.flags.append("estimate_override")
            p.provenance = {
                "assumption": True,
                "formula": FORMULA,
                "worked": f"ceil({est_mod.dstr(qty)} {unit} × {h} {rate['unit']} ÷ ({crew} × {cal['hours_per_day']} h)) = {days}",
                "quantity": est_mod.dstr(qty),
                "quantity_unit": unit,
                "quantity_field": qfield,
                "elements": n_el,
                "labour_h_per_unit": str(h),
                "rate_unit": rate["unit"],
                "range": {"low": rate["low"], "high": rate["high"], "use": rate["use"]} if "use" in rate else None,
                "scope": rate.get("scope"),
                "source": rate["source"],
                "crew": crew,
                "crew_source": crew_src,
                "crew_note": rate.get("crew_note"),
                "hours_per_day": cal["hours_per_day"],
                "calendar": cal["label"],
                "logic_note": LOGIC_NOTE,
            }

    def below(s: str) -> str | None:
        i = storeys.index(s)
        return storeys[i - 1] if i > 0 else None

    for (code, s), p in slots.items():
        lg = logic.get(code) or {}
        preds: list[Slot] = []
        for ref in lg.get("after", []):
            if ref not in by_rule:
                continue
            if ref in per_storey_rules and s and (ref, s) in slots:
                preds.append((ref, s))
            else:
                preds.extend(by_rule[ref])
        if s:
            for ref in lg.get("after_below", []):
                b_s = below(s)
                if b_s is not None and (ref, b_s) in slots:
                    preds.append((ref, b_s))
            b_s = below(s)
            if b_s is not None and (code, b_s) in slots:
                preds.append((code, b_s))  # the same crew moves up a storey
        raw_preds[(code, s)] = preds

    memo: dict[Slot, list[Slot]] = {}

    def resolve(slot: Slot, stack: frozenset[Slot]) -> list[Slot]:
        if slot in memo:
            return memo[slot]
        if slot in stack:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Schedule logic has a cycle at {slot}")
        out: list[Slot] = []
        for pr in raw_preds.get(slot, []):
            got = [pr] if slots[pr].active else resolve(pr, stack | {slot})
            out.extend(x for x in got if x not in out)
        memo[slot] = out
        return out

    for slot, p in slots.items():
        p.preds = resolve(slot, frozenset())

    order: list[Slot] = []
    seen: set[Slot] = set()

    def visit(slot: Slot, stack: frozenset[Slot]) -> None:
        if slot in seen:
            return
        if slot in stack:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Schedule logic has a cycle at {slot}")
        for pr in slots[slot].preds:
            visit(pr, stack | {slot})
        seen.add(slot)
        order.append(slot)

    for slot in slots:
        if slots[slot].active:
            visit(slot, frozenset())
    return Plan(slots, order, storeys, rate_missing, not_scheduled, cal)


# ── networks and CPM ────────────────────────────────────────────────────────


def _overridden(current: int, b: DesignScheduleBinding, new_model: int) -> bool:
    """A person set the duration: it differs from what this module wrote and from what the rates give now."""
    if b.last_applied_duration is None:
        return False
    if b.model_duration is not None and current == b.model_duration:
        return False
    return current != b.last_applied_duration and current != new_model


async def _schedule_bits(session, sched: DesignSchedule):
    from app.modules.schedule.service import ScheduleService

    svc = ScheduleService(session)
    schedule = await svc.get_schedule(sched.schedule_id)
    acts, _ = await svc.activity_repo.list_for_schedule(sched.schedule_id, limit=None)
    rels = await svc.relationship_repo.list_for_schedule(sched.schedule_id)
    calendar = await svc._resolve_schedule_default_calendar(schedule)
    return svc, schedule, acts, rels, calendar


def _project_start(schedule, acts) -> date:
    from app.modules.schedule.service import ScheduleService

    return ScheduleService._resolve_project_start(schedule, acts)


async def _cpm(acts: list[dict[str, Any]], edges: list[tuple[str, str]], calendar: dict, start: date) -> dict[str, Any]:
    from app.core.cpm import calculate_cpm, offset_to_iso

    if not acts:
        return {"finish": None, "days": 0, "critical": []}
    ids = {a["id"] for a in acts}
    rels = [
        {"predecessor_id": p, "successor_id": s, "type": "FS", "lag": 0}
        for p, s in dict.fromkeys(edges)
        if p in ids and s in ids
    ]
    succ = {r["successor_id"] for r in rels}
    for a in acts:
        if a["id"] in succ:
            a["start_offset"] = 0
    res = await calculate_cpm(acts, rels, calendar=calendar, project_start_date=start.isoformat())
    finish = max((r["early_finish"] for r in res), default=0)
    return {
        "finish": offset_to_iso(finish, start),
        "days": finish,
        "critical": [r["id"] for r in res if r.get("is_critical")],
    }


def _edges_of(acts, rels) -> list[tuple[str, str]]:
    from app.modules.schedule.service import _normalize_deps

    if rels:
        return [(str(r.predecessor_id), str(r.successor_id)) for r in rels]
    out = []
    for a in acts:
        for d in _normalize_deps(a.dependencies):
            out.append((str(d.get("activity_id", "")), str(a.id)))
    return out


def _network(acts, start: date) -> list[dict[str, Any]]:
    from app.modules.schedule.service import ScheduleService

    return [
        {
            "id": str(a.id),
            "duration": a.duration_days or 0,
            "name": a.name or "",
            "start_offset": ScheduleService._activity_start_offset(a, start),
        }
        for a in acts
        if (a.activity_type or "task") != "summary"
    ]


async def _context(session, project_id: uuid.UUID):
    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == project_id))
    ).scalar_one_or_none()
    sched = (
        await session.execute(select(DesignSchedule).where(DesignSchedule.project_id == project_id))
    ).scalar_one_or_none()
    return est, sched


async def _binding_map(session, project_id: uuid.UUID) -> dict[Slot, DesignScheduleBinding]:
    rows = (
        await session.execute(select(DesignScheduleBinding).where(DesignScheduleBinding.project_id == project_id))
    ).scalars()
    return {(b.rule_code, b.storey): b for b in rows}


# ── impact of a pending revision ────────────────────────────────────────────


async def impact(session, rev: DesignRevision) -> dict[str, Any]:
    """Schedule delta if ``rev`` were accepted now: the ERP's CPM on the network before and after. Writes nothing."""
    out: dict[str, Any] = {"schema": IMPACT_SCHEMA, "revision_id": str(rev.id), "schedule": False}
    est, sched = await _context(session, rev.project_id)
    if est is None or sched is None or rev.bim_model_id is None:
        return out
    rates = rates_for(est.country, est.use)
    if rates is None:
        return out
    plan = await build_plan(session, est, sched, rates, rev.bim_model_id)
    _, schedule, acts, rels, calendar = await _schedule_bits(session, sched)
    start = _project_start(schedule, acts)
    bindings = await _binding_map(session, rev.project_id)
    by_id = {str(a.id): a for a in acts}
    cur_net = _network(acts, start)
    cur_edges = _edges_of(acts, rels)
    bound_ids = {str(b.activity_id) for b in bindings.values() if str(b.activity_id) in by_id}
    slot_id: dict[Slot, str] = {}
    rows: list[dict[str, Any]] = []
    new_dur: dict[str, int] = {}
    added: list[dict[str, Any]] = []
    for slot, p in plan.slots.items():
        b = bindings.get(slot)
        a = by_id.get(str(b.activity_id)) if b else None
        new_model = p.duration if p.active else 0
        if a is None and not p.active:
            continue
        if a is not None:
            cur = a.duration_days or 0
            override = _overridden(cur, b, new_model)
            eff = cur if override else new_model
            slot_id[slot] = str(a.id)
            new_dur[str(a.id)] = eff
        else:
            cur, override, eff = None, False, new_model
            nid = f"new:{slot[0]}:{slot[1]}"
            slot_id[slot] = nid
            added.append({"id": nid, "duration": eff, "name": p.label, "start_offset": 0})
        flags = sorted(set(p.flags + (["override"] if override else []) + ([] if p.active else ["no_match"])))
        rows.append(
            {
                "rule": p.rule,
                "label": p.label,
                "storey": p.storey,
                "activity_id": str(a.id) if a else None,
                "new_activity": a is None,
                "current_days": cur,
                "model_days_now": b.model_duration if b else None,
                "model_days_new": new_model,
                "new_days": eff,
                "delta_days": eff - (cur or 0),
                "override": override,
                "override_days": cur if override else None,
                "flags": flags,
                "quantity": est_mod.dstr(p.quantity),
                "unit": p.unit,
                "provenance": p.provenance,
            }
        )
    after_net = [{**n, "duration": new_dur.get(n["id"], n["duration"])} for n in cur_net] + added
    design_ids = bound_ids | {x["id"] for x in added}
    after_edges = [(pr, su) for pr, su in cur_edges if not (pr in design_ids and su in design_ids)]
    for slot, p in plan.slots.items():
        if slot in slot_id and p.active:
            after_edges.extend((slot_id[pr], slot_id[slot]) for pr in p.preds if pr in slot_id)
    before = await _cpm([dict(n) for n in cur_net], cur_edges, calendar, start)
    after = await _cpm(after_net, after_edges, calendar, start)
    rows.sort(
        key=lambda r: (
            not r["override"],
            r["delta_days"] == 0,
            plan.storeys.index(r["storey"]) if r["storey"] in plan.storeys else -1,
            r["rule"],
        )
    )
    out.update(
        {
            "schedule": True,
            "schedule_id": str(sched.schedule_id),
            "start": start.isoformat(),
            "rows": rows,
            "totals": {
                "current_finish": before["finish"],
                "after_finish": after["finish"],
                "current_days": before["days"],
                "after_days": after["days"],
                "delta_days": after["days"] - before["days"],
                "activities_added": len(added),
                "overrides_kept": sum(1 for r in rows if r["override"]),
            },
            "rate_missing": plan.rate_missing,
            "not_scheduled": plan.not_scheduled,
            "complete": not plan.rate_missing,
            "calendar": plan.calendar,
            "formula": FORMULA,
            "logic_note": LOGIC_NOTE,
        }
    )
    return out


# ── apply (accept, setup) ───────────────────────────────────────────────────


def _name(p: Planned) -> str:
    return (f"{p.label} · {p.storey}" if p.storey else p.label)[:255]


def _meta(p: Planned, rev_id: uuid.UUID, flags: list[str]) -> dict[str, Any]:
    return {
        "design": {
            "rule": p.rule,
            "storey": p.storey,
            "revision_id": str(rev_id),
            "flags": flags,
            "quantity": est_mod.dstr(p.quantity),
            "unit": p.unit,
            "provenance": p.provenance,
        }
    }


async def recompute(session, project_id: uuid.UUID, rev_id: uuid.UUID, model_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Make the design schedule follow the model of ``model_id``. Flushes. Returns the activities written."""
    from app.modules.schedule.schemas import ActivityCreate, ActivityDependency, ActivityUpdate

    est, sched = await _context(session, project_id)
    if est is None or sched is None:
        return 0
    rates = rates_for(est.country, est.use)
    if rates is None:
        return 0
    plan = await build_plan(session, est, sched, rates, model_id)
    svc, schedule, acts, rels, _ = await _schedule_bits(session, sched)
    start = (schedule.start_date or date.today().isoformat())[:10]
    by_id = {a.id: a for a in acts}
    bindings = await _binding_map(session, project_id)
    design_ids = {b.activity_id for b in bindings.values()}
    slot_id: dict[Slot, uuid.UUID] = {}
    written = 0
    actor = str(user_id)

    async def end_of(days: int) -> str:
        return await svc.working_end_date(project_id, None, start, days) if days > 0 else start

    for slot in plan.order:
        p = plan.slots[slot]
        b = bindings.get(slot)
        a = by_id.get(b.activity_id) if b else None
        deps_design = [slot_id[pr] for pr in p.preds if pr in slot_id]
        if a is None:
            deps = [ActivityDependency(activity_id=i) for i in deps_design]
            new = await svc.create_activity(
                ActivityCreate(
                    schedule_id=sched.schedule_id,
                    name=_name(p),
                    start_date=start,
                    end_date=await end_of(p.duration),
                    duration_days=p.duration,
                    dependencies=deps,
                    boq_position_ids=[p.position_id] if p.position_id else [],
                    description=p.provenance.get("worked", ""),
                    metadata=_meta(p, rev_id, p.flags),
                ),
                actor_id=actor,
            )
            if b is None:
                b = DesignScheduleBinding(project_id=project_id, rule_code=p.rule, storey=p.storey, activity_id=new.id)
                session.add(b)
                bindings[slot] = b
            else:
                b.activity_id = new.id
            design_ids.add(new.id)
            slot_id[slot] = new.id
            b.model_duration = b.last_applied_duration = p.duration
            b.flags, b.provenance, b.revision_id = sorted(set(p.flags)), p.provenance, rev_id
            written += 1
            continue
        slot_id[slot] = a.id
        cur = a.duration_days or 0
        override = _overridden(cur, b, p.duration)
        kept = [
            d["activity_id"]
            for d in (a.dependencies or [])
            if isinstance(d, dict) and _uuid(d.get("activity_id")) not in design_ids
        ]
        deps = [ActivityDependency(activity_id=i) for i in [*deps_design, *(_uuid(k) for k in kept)] if i]
        flags = sorted(set(p.flags + (["override"] if override else [])))
        upd: dict[str, Any] = {
            "dependencies": deps,
            "metadata": merge_metadata(a.metadata_, _meta(p, rev_id, flags)),
            "description": p.provenance.get("worked", ""),
        }
        if not override and cur != p.duration:
            upd.update(_duration_fields(a, p.duration))
        if p.position_id and str(p.position_id) not in {str(x) for x in (a.boq_position_ids or [])}:
            upd["boq_position_ids"] = [*(a.boq_position_ids or []), p.position_id]
        await svc.update_activity(a.id, ActivityUpdate(**upd), actor_id=actor)
        b.model_duration = p.duration
        if not override:
            b.last_applied_duration = p.duration
        b.flags, b.provenance, b.revision_id = flags, p.provenance, rev_id
        written += 1

    # Bound activities the plan no longer has: kept, flagged, zero days unless a person set them.
    for slot, b in bindings.items():
        if slot in slot_id:
            continue
        a = by_id.get(b.activity_id)
        if a is None:
            continue
        p = plan.slots.get(slot)
        cur = a.duration_days or 0
        override = _overridden(cur, b, 0)
        flags = sorted(set((p.flags if p else []) + ["no_match"] + (["override"] if override else [])))
        upd = {
            "metadata": {
                **(a.metadata_ or {}),
                "design": {**((a.metadata_ or {}).get("design") or {}), "flags": flags, "revision_id": str(rev_id)},
            }
        }
        if not override and cur != 0:
            upd.update(_duration_fields(a, 0))
        await svc.update_activity(a.id, ActivityUpdate(**upd), actor_id=actor)
        b.model_duration = 0
        if not override:
            b.last_applied_duration = 0
        b.flags, b.revision_id = flags, rev_id
    sched.revision_id = rev_id
    await session.flush()
    if written or bindings:
        await _reschedule(session, svc, sched.schedule_id)
    return written


async def _reschedule(session, svc, schedule_id: uuid.UUID) -> None:
    """ERP CPM pass. Its bulk update expires the whole session, so the caller's rows are reloaded here:
    the accept flow keeps using its revision, estimate and binding objects after this call."""
    from app.modules.schedule.models import Activity

    keep = [o for o in list(session.identity_map.values()) if not isinstance(o, Activity)]
    await svc.reschedule(schedule_id)
    await svc.sync_schedule_end_date(schedule_id)
    for o in keep:
        if o in session:
            await session.refresh(o)


def _duration_fields(a, days: int) -> dict[str, Any]:
    """Fields that set an activity to `days` working days. The duration is sent alone, so the ERP moves the end date
    on the activity's own start and calendar; zero days makes it a milestone, more days a task again."""
    out: dict[str, Any] = {"duration_days": days}
    if days > 0 and a.activity_type == "milestone":
        out["activity_type"] = "task"  # work came back into the model
    return out


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v))
    except (TypeError, ValueError):
        return None


async def recompute_on_accept(
    session, project_id: uuid.UUID, revision_id: uuid.UUID, model_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await recompute(session, project_id, revision_id, model_id, user_id)


async def setup(session, project_id: uuid.UUID, start_date: str | None, user_id: uuid.UUID) -> DesignSchedule:
    """Create the design schedule (an ERP schedule) and plan it from the revision the estimate follows."""
    from app.modules.projects.models import Project
    from app.modules.schedule.schemas import ScheduleCreate
    from app.modules.schedule.service import ScheduleService

    est, sched = await _context(session, project_id)
    if est is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Set up the design estimate first: activities follow its positions"
        )
    if sched is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The project already has a design schedule")
    if rates_for(est.country, est.use) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No sourced productivity rates for {est.country} {est.use}")
    project = await session.get(Project, project_id)
    planned = getattr(project, "planned_start_date", None)
    start, start_source = (
        (start_date, "given")
        if start_date
        else ((str(planned)[:10], "project_planned_start") if planned else (date.today().isoformat(), "today"))
    )
    svc = ScheduleService(session)
    schedule = await svc.create_schedule(
        ScheduleCreate(
            project_id=project_id,
            name="Design schedule",
            start_date=start,
            created_by=user_id,
            description="Activities from accepted design revisions: estimate positions × storeys, durations from sourced "
            "productivity rates (each one an assumption with its formula).",
            metadata={"design": {"start_source": start_source}},
        )
    )
    sched = DesignSchedule(project_id=project_id, schedule_id=schedule.id, country=est.country, use=est.use, crews={})
    session.add(sched)
    await session.flush()
    if est.revision_id is not None:
        rev = await session.get(DesignRevision, est.revision_id)
        if rev is not None and rev.bim_model_id is not None:
            await recompute(session, project_id, rev.id, rev.bim_model_id, user_id)
    return sched


async def set_crews(session, project_id: uuid.UUID, crews: dict[str, int]) -> DesignSchedule:
    _, sched = await _context(session, project_id)
    if sched is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The project has no design schedule")
    rates = rates_for(sched.country, sched.use) or {"rates": {}}
    unknown = [c for c in crews if c not in rates["rates"]]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown rules: {', '.join(sorted(unknown))}")
    sched.crews = {k: v for k, v in crews.items() if v}
    await session.flush()
    return sched


# ── read ────────────────────────────────────────────────────────────────────


async def summary(session, project_id: uuid.UUID) -> dict[str, Any]:
    est, sched = await _context(session, project_id)
    if sched is None:
        rates = rates_for(est.country, est.use) if est is not None else None
        return {"schedule": False, "estimate": est is not None, "rates_available": rates is not None}
    rates = rates_for(sched.country, sched.use) or {"rates": {}}
    _, schedule, acts, rels, calendar = await _schedule_bits(session, sched)
    start = _project_start(schedule, acts)
    bindings = await _binding_map(session, project_id)
    by_id = {a.id: a for a in acts}
    cpm = await _cpm(_network(acts, start), _edges_of(acts, rels), calendar, start)
    rows = []
    for (code, storey), b in bindings.items():
        a = by_id.get(b.activity_id)
        if a is None:
            continue
        override = _overridden(a.duration_days or 0, b, b.model_duration or 0)
        rows.append(
            {
                "rule": code,
                "storey": storey,
                "activity_id": str(a.id),
                "name": a.name,
                "start": a.start_date,
                "end": a.end_date,
                "days": a.duration_days,
                "model_days": b.model_duration,
                "override": override,
                "flags": sorted(
                    set([f for f in (b.flags or []) if f != "override"] + (["override"] if override else []))
                ),
                "boq_position_ids": [str(x) for x in (a.boq_position_ids or [])],
                "provenance": b.provenance,
            }
        )
    rows.sort(key=lambda r: (r["start"] or "", r["rule"], r["storey"]))
    rule_rows = {r.code: r for r in await est_mod._rule_rows(session, project_id)} if est else {}
    missing = [
        {"rule": c, "label": rule_rows[c].body["label"] if c in rule_rows else c, "missing": e["missing"]}
        for c, e in rates["rates"].items()
        if e.get("labour_h_per_unit", 0) is None
    ]
    skipped = [
        {"rule": c, "label": rule_rows[c].body["label"] if c in rule_rows else c, "reason": e["not_scheduled"]}
        for c, e in rates["rates"].items()
        if "not_scheduled" in e
    ]
    return {
        "schedule": True,
        "schedule_id": str(sched.schedule_id),
        "url": SCHEDULE_URL,
        "revision_id": str(sched.revision_id) if sched.revision_id else None,
        "country": sched.country,
        "use": sched.use,
        "start": start.isoformat(),
        "finish": cpm["finish"],
        "days": cpm["days"],
        "activities": rows,
        "rate_missing": missing,
        "not_scheduled": skipped,
        "complete": not missing,
        "crews": sched.crews or {},
        "calendar": calendar_for(sched.country),
        "formula": FORMULA,
        "logic_note": LOGIC_NOTE,
    }


# ── change orders (R9) ──────────────────────────────────────────────────────


def for_change_order(imp: dict[str, Any] | None) -> dict[str, Any] | None:
    if not imp or not imp.get("schedule"):
        return None
    t = imp["totals"]
    return {
        "delta_days": t["delta_days"],
        "current_finish": t["current_finish"],
        "after_finish": t["after_finish"],
        "complete": imp["complete"],
        "rate_missing": [r["rule"] for r in imp["rate_missing"]],
        "overrides_kept": t["overrides_kept"],
        "schedule_id": imp["schedule_id"],
    }
