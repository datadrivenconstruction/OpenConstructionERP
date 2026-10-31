# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure dispatch board rules: conflicts, unit status, scheduled moves, utilisation, timesheet prefill.

No database access here. The service loads plain dicts and hands them in, so every rule
is testable without PostgreSQL and the validators reuse the same functions.

Card kinds: ``crew`` (a dispatch crew of resource ids), ``worker`` (a resources person),
``equipment`` (an equipment unit), ``rental`` (an equipment rental, which names its unit).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

CARD_KINDS = ("crew", "worker", "equipment", "rental")
LOCATION_KINDS = ("project", "yard", "shop", "rental_return")
ABSENCE_WINDOWS = ("unavailable", "holiday", "sick", "leave")
OPEN_WORK_ORDER = ("scheduled", "in_progress")

# Conflict kinds, each backed by one validation rule (see validators.py).
DOUBLE_BOOKED = "double_booked"
MISSING_CERTIFICATE = "missing_certificate"
MAINTENANCE_OVERDUE = "maintenance_overdue"
MAINTENANCE_BLOCK = "maintenance_block"
WORKER_ABSENT = "worker_absent"
CREW_UNDER_MINIMUM = "crew_under_minimum"
CONFLICT_KINDS = (
    DOUBLE_BOOKED,
    MISSING_CERTIFICATE,
    MAINTENANCE_OVERDUE,
    MAINTENANCE_BLOCK,
    WORKER_ABSENT,
    CREW_UNDER_MINIMUM,
)
ERROR_KINDS = frozenset({DOUBLE_BOOKED, MAINTENANCE_BLOCK})


@dataclass
class Conflict:
    """One problem on the board for one day, never hidden from the dispatcher."""

    kind: str
    card_kind: str
    card_ref: str
    message: str
    severity: str = "warning"
    placement_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "card_kind": self.card_kind,
            "card_ref": self.card_ref,
            "message": self.message,
            "severity": self.severity,
            "placement_ids": list(self.placement_ids),
            "details": dict(self.details),
        }


@dataclass
class DayFacts:
    """Everything the conflict rules need for one day, loaded by the service.

    placements: ``[{"id", "card_kind", "card_ref", "location_id", "location_kind", "operator_ref"}]``
    crews: ``{crew_id: {"name", "member_ids": [...], "min_size"}}``
    rentals: ``{rental_id: equipment_id}``
    work_orders: ``{equipment_id: [{"scheduled_for": "YYYY-MM-DD", "status"}]}``
    equipment_status: ``{equipment_id: status}``
    required_certs: ``{equipment_id: [cert_type, ...]}``
    valid_certs: ``{resource_id: {cert_type, ...}}`` valid on the day
    absences: ``{resource_id: window_type}`` for windows covering the day
    names: ``{(card_kind, ref): label}`` for readable messages
    """

    day: date
    placements: list[dict[str, Any]] = field(default_factory=list)
    crews: dict[str, dict[str, Any]] = field(default_factory=dict)
    rentals: dict[str, str] = field(default_factory=dict)
    work_orders: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    equipment_status: dict[str, str] = field(default_factory=dict)
    required_certs: dict[str, list[str]] = field(default_factory=dict)
    valid_certs: dict[str, set[str]] = field(default_factory=dict)
    absences: dict[str, str] = field(default_factory=dict)
    names: dict[tuple[str, str], str] = field(default_factory=dict)

    def label(self, kind: str, ref: str) -> str:
        return self.names.get((kind, ref)) or ref[:8]


def _iso(value: Any) -> str:
    return str(value or "")[:10]


def unit_blocked(equipment_id: str, day: date, facts: DayFacts) -> bool:
    """A unit is down on a day when it is marked under maintenance or a work order holds it.

    A scheduled order blocks its own day; an order in progress blocks every day from its
    date until it is completed.
    """
    if facts.equipment_status.get(equipment_id) == "under_maintenance":
        return True
    d = day.isoformat()
    for wo in facts.work_orders.get(equipment_id, []):
        when = _iso(wo.get("scheduled_for"))
        status = str(wo.get("status") or "")
        if not when:
            continue
        if status == "scheduled" and when == d:
            return True
        if status == "in_progress" and when <= d:
            return True
    return False


def maintenance_overdue(equipment_id: str, day: date, facts: DayFacts) -> list[str]:
    """Dates of scheduled work orders that should have been done before ``day``."""
    d = day.isoformat()
    return sorted(
        _iso(wo.get("scheduled_for"))
        for wo in facts.work_orders.get(equipment_id, [])
        if wo.get("status") == "scheduled" and _iso(wo.get("scheduled_for")) and _iso(wo.get("scheduled_for")) < d
    )


def placement_equipment_id(p: dict[str, Any], facts: DayFacts) -> str | None:
    if p["card_kind"] == "equipment":
        return str(p["card_ref"])
    if p["card_kind"] == "rental":
        return facts.rentals.get(str(p["card_ref"]))
    return None


def placement_people(p: dict[str, Any], facts: DayFacts) -> list[str]:
    """Resource ids a placement puts on site: the worker, the crew members, the operator."""
    people: list[str] = []
    if p["card_kind"] == "worker":
        people.append(str(p["card_ref"]))
    elif p["card_kind"] == "crew":
        people.extend(str(m) for m in facts.crews.get(str(p["card_ref"]), {}).get("member_ids") or [])
    if p.get("operator_ref"):
        people.append(str(p["operator_ref"]))
    return people


def unit_status(equipment_id: str, facts: DayFacts, in_transit: set[str] | None = None) -> str:
    """Colour of an equipment card: available, assigned, maintenance or in_transit."""
    if unit_blocked(equipment_id, facts.day, facts):
        return "maintenance"
    if in_transit and equipment_id in in_transit:
        return "in_transit"
    for p in facts.placements:
        if placement_equipment_id(p, facts) == equipment_id and p.get("location_kind") == "project":
            return "assigned"
    return "available"


def detect_conflicts(facts: DayFacts) -> list[Conflict]:
    """Every conflict on one day's board. Order: by kind, then by card."""
    out: list[Conflict] = []
    day = facts.day

    # Same person or unit at two locations on the same day, crews expanded to members.
    people_at: dict[str, dict[str, list[str]]] = {}
    units_at: dict[str, dict[str, list[str]]] = {}
    for p in facts.placements:
        for rid in placement_people(p, facts):
            people_at.setdefault(rid, {}).setdefault(str(p["location_id"]), []).append(str(p["id"]))
        eq = placement_equipment_id(p, facts)
        if eq:
            units_at.setdefault(eq, {}).setdefault(str(p["location_id"]), []).append(str(p["id"]))
    for kind, table in (("worker", people_at), ("equipment", units_at)):
        for ref, by_loc in table.items():
            if len(by_loc) > 1:
                ids = [pid for pids in by_loc.values() for pid in pids]
                out.append(
                    Conflict(
                        DOUBLE_BOOKED,
                        kind,
                        ref,
                        f"{facts.label(kind, ref)} is placed at {len(by_loc)} locations on {day.isoformat()}.",
                        "error",
                        ids,
                        {"locations": sorted(by_loc)},
                    )
                )

    for p in facts.placements:
        eq = placement_equipment_id(p, facts)
        if not eq:
            continue
        pid = str(p["id"])
        if unit_blocked(eq, day, facts) and p.get("location_kind") == "project":
            out.append(
                Conflict(
                    MAINTENANCE_BLOCK,
                    "equipment",
                    eq,
                    f"{facts.label('equipment', eq)} is down for maintenance on {day.isoformat()}.",
                    "error",
                    [pid],
                )
            )
        overdue = maintenance_overdue(eq, day, facts)
        if overdue:
            out.append(
                Conflict(
                    MAINTENANCE_OVERDUE,
                    "equipment",
                    eq,
                    f"{facts.label('equipment', eq)} is past due for maintenance (due {overdue[0]}).",
                    "warning",
                    [pid],
                    {"due": overdue},
                )
            )
        required = [c for c in facts.required_certs.get(eq, []) if c]
        operator = str(p.get("operator_ref") or "")
        if required and operator:
            held = facts.valid_certs.get(operator, set())
            missing = [c for c in required if c not in held]
            if missing:
                out.append(
                    Conflict(
                        MISSING_CERTIFICATE,
                        "worker",
                        operator,
                        f"{facts.label('worker', operator)} has no valid {', '.join(missing)} "
                        f"for {facts.label('equipment', eq)}.",
                        "warning",
                        [pid],
                        {"missing": missing, "equipment_id": eq},
                    )
                )

    seen_absent: set[str] = set()
    for p in facts.placements:
        for rid in placement_people(p, facts):
            window = facts.absences.get(rid)
            if window and rid not in seen_absent:
                seen_absent.add(rid)
                out.append(
                    Conflict(
                        WORKER_ABSENT,
                        "worker",
                        rid,
                        f"{facts.label('worker', rid)} is absent ({window}) on {day.isoformat()}.",
                        "warning",
                        [str(p["id"])],
                        {"window": window},
                    )
                )
        if p["card_kind"] == "crew":
            crew = facts.crews.get(str(p["card_ref"])) or {}
            members = [str(m) for m in crew.get("member_ids") or []]
            present = [m for m in members if m not in facts.absences]
            minimum = int(crew.get("min_size") or 0)
            if minimum and len(present) < minimum:
                out.append(
                    Conflict(
                        CREW_UNDER_MINIMUM,
                        "crew",
                        str(p["card_ref"]),
                        f"{facts.label('crew', str(p['card_ref']))} has {len(present)} of the {minimum} people it needs.",
                        "warning",
                        [str(p["id"])],
                        {"present": len(present), "minimum": minimum},
                    )
                )
    order = {k: i for i, k in enumerate(CONFLICT_KINDS)}
    out.sort(key=lambda c: (order.get(c.kind, 99), c.card_kind, c.card_ref))
    return out


def plan_move(
    placements: list[dict[str, Any]], card_kind: str, card_ref: str, to_location_id: str
) -> tuple[list[str], bool]:
    """What applying a move does to one day: ids to delete and whether to create at the target.

    The card leaves every other location that day; if it is already at the target nothing
    is created, so applying twice changes nothing.
    """
    mine = [p for p in placements if p["card_kind"] == card_kind and str(p["card_ref"]) == card_ref]
    remove = [str(p["id"]) for p in mine if str(p["location_id"]) != to_location_id]
    create = not any(str(p["location_id"]) == to_location_id for p in mine)
    return remove, create


def due_moves(moves: Iterable[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Pending moves whose date has come, oldest first so a later move wins."""
    due = [m for m in moves if m.get("status") == "pending" and m["effective_date"] <= today]
    return sorted(due, key=lambda m: (m["effective_date"], str(m.get("created_at") or "")))


def working_days(start: date, end: date) -> list[date]:
    """Monday to Friday in [start, end]."""
    out: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def utilisation(
    placements: Iterable[dict[str, Any]], units: Iterable[str], start: date, end: date
) -> list[dict[str, Any]]:
    """Per unit: working days on a project vs idle in [start, end]; idle days are the rental saving."""
    days = working_days(start, end)
    day_set = set(days)
    on_job: dict[str, set[date]] = {}
    for p in placements:
        if p.get("location_kind") != "project" or p["day"] not in day_set:
            continue
        on_job.setdefault(str(p["unit_ref"]), set()).add(p["day"])
    rows = []
    for u in units:
        assigned = len(on_job.get(u, set()))
        total = len(days)
        rows.append(
            {
                "unit_ref": u,
                "days_assigned": assigned,
                "days_idle": total - assigned,
                "working_days": total,
                "percent": round(100 * assigned / total) if total else 0,
                "assigned_days": sorted(d.isoformat() for d in on_job.get(u, set())),
            }
        )
    rows.sort(key=lambda r: (r["percent"], r["unit_ref"]))
    return rows


def timesheet_lines(
    placements: Iterable[dict[str, Any]],
    crews: dict[str, dict[str, Any]],
    rentals: dict[str, str],
    *,
    hours: Any,
    existing_resources: set[str] | None = None,
    existing_equipment: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Timesheet lines for the dispatched people and machines at one site, each once.

    Lines already on the timesheet are skipped so a second prefill only adds who was
    dispatched since.
    """
    have_r = set(existing_resources or set())
    have_e = set(existing_equipment or set())
    lines: list[dict[str, Any]] = []
    facts = DayFacts(day=date.today(), crews=crews, rentals=rentals)
    for p in placements:
        for rid in placement_people(p, facts):
            if rid not in have_r:
                have_r.add(rid)
                lines.append({"resource_id": rid, "hours": hours, "note": p.get("notes") or None})
        eq = placement_equipment_id(p, facts)
        if eq and eq not in have_e:
            have_e.add(eq)
            lines.append({"equipment_id": eq, "hours": hours, "note": p.get("notes") or None})
    return lines
