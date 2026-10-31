# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board business logic.

Loads people, certificates and absences from resources, units, work orders and rentals from
equipment, and turns them into the plain facts ``logic`` works on. Writes only dispatch
tables, plus a draft field timesheet when a foreman asks for the prefill.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dispatch import logic
from app.modules.dispatch.models import (
    DispatchCrew,
    DispatchLocation,
    DispatchPlacement,
    DispatchScheduledMove,
    DispatchViewPref,
)
from app.modules.dispatch.repository import DispatchRepository, _is_uuid
from app.modules.dispatch.schemas import (
    CopyDayRequest,
    CrewCreate,
    CrewUpdate,
    LocationCreate,
    LocationUpdate,
    MoveRequest,
    PlacementUpdate,
    PlaceRequest,
    PrefillRequest,
    ScheduleMoveRequest,
    ViewPref,
)

logger = logging.getLogger(__name__)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _today() -> date:
    return datetime.now(UTC).date()


class DispatchService:
    """Board reads and writes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DispatchRepository(session)
        self._in_transit: set[str] = set()

    # ── Locations and crews ─────────────────────────────────────────────

    async def create_location(self, data: LocationCreate) -> DispatchLocation:
        if data.kind == "project" and data.project_id is None:
            raise HTTPException(status_code=422, detail="A project column needs a project")
        loc = DispatchLocation(
            name=data.name, kind=data.kind, project_id=data.project_id, sort_order=data.sort_order, is_active=True
        )
        await self.repo.add(loc)
        return loc

    async def update_location(self, location_id: uuid.UUID, data: LocationUpdate) -> DispatchLocation:
        loc = await self.repo.get_location(location_id)
        if loc is None:
            raise _not_found("Location")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(loc, key, value)
        await self.session.flush()
        return loc

    async def create_crew(self, data: CrewCreate) -> DispatchCrew:
        crew = DispatchCrew(
            name=data.name,
            foreman_resource_id=str(data.foreman_resource_id) if data.foreman_resource_id else None,
            foreman_user_id=data.foreman_user_id,
            member_ids=[str(m) for m in data.member_ids],
            min_size=data.min_size,
            trade=data.trade,
            labor_crew_id=data.labor_crew_id,
            is_active=True,
        )
        await self.repo.add(crew)
        return crew

    async def update_crew(self, crew_id: uuid.UUID, data: CrewUpdate) -> DispatchCrew:
        crew = await self.repo.get_crew(crew_id)
        if crew is None:
            raise _not_found("Crew")
        for key, value in data.model_dump(exclude_unset=True).items():
            if key == "member_ids" and value is not None:
                value = [str(m) for m in value]
            if key == "foreman_resource_id" and value is not None:
                value = str(value)
            setattr(crew, key, value)
        await self.session.flush()
        return crew

    # ── Card catalogue ──────────────────────────────────────────────────

    async def cards(self, kind: str, q: str = "", *, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        """Cards the dispatcher can drag onto the board, one kind at a time, paginated."""
        from app.modules.equipment.models import Equipment, EquipmentRental
        from app.modules.resources.models import Resource

        like = f"%{q.strip()}%" if q.strip() else None
        if kind == "worker":
            stmt = select(Resource).where(Resource.resource_type == "person", Resource.status != "inactive")
            if like:
                stmt = stmt.where(or_(Resource.name.ilike(like), Resource.code.ilike(like)))
            order = Resource.name
            rows_to = lambda r: {"card_kind": "worker", "card_ref": str(r.id), "label": r.name, "subtitle": r.code}  # noqa: E731
        elif kind == "equipment":
            stmt = select(Equipment).where(Equipment.status != "decommissioned")
            if like:
                stmt = stmt.where(or_(Equipment.name.ilike(like), Equipment.code.ilike(like)))
            order = Equipment.code
            rows_to = lambda e: {  # noqa: E731
                "card_kind": "equipment",
                "card_ref": str(e.id),
                "label": f"{e.code} {e.name}",
                "subtitle": e.type_code,
                "status": "maintenance" if e.status == "under_maintenance" else "",
            }
        elif kind == "rental":
            stmt = (
                select(EquipmentRental, Equipment.code, Equipment.name)
                .join(Equipment, Equipment.id == EquipmentRental.equipment_id)
                .where(EquipmentRental.status == "active")
            )
            if like:
                stmt = stmt.where(or_(Equipment.name.ilike(like), Equipment.code.ilike(like)))
            total = int((await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0)
            rows = (await self.session.execute(stmt.order_by(Equipment.code).limit(limit).offset(offset))).all()
            items = [
                {
                    "card_kind": "rental",
                    "card_ref": str(r.id),
                    "label": f"{code} {name}",
                    "subtitle": f"{r.start_date} - {r.end_date or ''}".strip(" -"),
                }
                for r, code, name in rows
            ]
            return items, total
        else:
            stmt = select(DispatchCrew).where(DispatchCrew.is_active.is_(True))
            if like:
                stmt = stmt.where(DispatchCrew.name.ilike(like))
            order = DispatchCrew.name
            rows_to = lambda c: {  # noqa: E731
                "card_kind": "crew",
                "card_ref": str(c.id),
                "label": c.name,
                "subtitle": f"{len(c.member_ids or [])} {c.trade}".strip(),
            }
        total = int((await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0)
        rows = (await self.session.execute(stmt.order_by(order).limit(limit).offset(offset))).scalars().all()
        return [rows_to(r) for r in rows], total

    # ── Facts for one day ───────────────────────────────────────────────

    async def _facts(self, day: date, placements: list[DispatchPlacement]) -> logic.DayFacts:
        from app.modules.equipment.models import Equipment, EquipmentRental, MaintenanceWorkOrder
        from app.modules.resources.models import AvailabilityWindow, Certification, Resource

        locs = {loc.id: loc for loc in await self.repo.list_locations(include_inactive=True)}
        rows = [
            {
                "id": str(p.id),
                "card_kind": p.card_kind,
                "card_ref": p.card_ref,
                "location_id": str(p.location_id),
                "location_kind": locs[p.location_id].kind if p.location_id in locs else "",
                "operator_ref": p.operator_ref,
                "notes": p.notes,
            }
            for p in placements
        ]
        facts = logic.DayFacts(day=day, placements=rows)

        crew_ids = {p.card_ref for p in placements if p.card_kind == "crew"}
        for c in await self.repo.crews_by_ids(crew_ids):
            facts.crews[str(c.id)] = {"name": c.name, "member_ids": list(c.member_ids or []), "min_size": c.min_size}
            facts.names[("crew", str(c.id))] = c.name

        rental_ids = [uuid.UUID(p.card_ref) for p in placements if p.card_kind == "rental" and _is_uuid(p.card_ref)]
        if rental_ids:
            for rid, eid in (
                await self.session.execute(
                    select(EquipmentRental.id, EquipmentRental.equipment_id).where(EquipmentRental.id.in_(rental_ids))
                )
            ).all():
                facts.rentals[str(rid)] = str(eid)

        unit_ids = {logic.placement_equipment_id(r, facts) for r in rows} - {None}
        unit_uuids = [uuid.UUID(u) for u in unit_ids if u and _is_uuid(u)]
        if unit_uuids:
            for e in (await self.session.execute(select(Equipment).where(Equipment.id.in_(unit_uuids)))).scalars():
                facts.equipment_status[str(e.id)] = e.status
                facts.required_certs[str(e.id)] = [
                    str(c) for c in (e.metadata_ or {}).get("required_certificates") or [] if c
                ]
                facts.names[("equipment", str(e.id))] = f"{e.code} {e.name}"
            for rid, label in list(facts.rentals.items()):
                facts.names[("rental", rid)] = facts.names.get(("equipment", label), "")
            wos = (
                await self.session.execute(
                    select(
                        MaintenanceWorkOrder.equipment_id,
                        MaintenanceWorkOrder.scheduled_for,
                        MaintenanceWorkOrder.status,
                    ).where(
                        MaintenanceWorkOrder.equipment_id.in_(unit_uuids),
                        MaintenanceWorkOrder.status.in_(logic.OPEN_WORK_ORDER),
                        MaintenanceWorkOrder.scheduled_for <= day.isoformat(),
                    )
                )
            ).all()
            for eid, when, st in wos:
                facts.work_orders.setdefault(str(eid), []).append({"scheduled_for": when, "status": st})

        people: set[str] = set()
        for r in rows:
            people.update(logic.placement_people(r, facts))
        people_uuids = [uuid.UUID(p) for p in people if _is_uuid(p)]
        if people_uuids:
            for rid, name in (
                await self.session.execute(select(Resource.id, Resource.name).where(Resource.id.in_(people_uuids)))
            ).all():
                facts.names[("worker", str(rid))] = name
            d = day.isoformat()
            for rid, ctype, valid_until in (
                await self.session.execute(
                    select(Certification.resource_id, Certification.cert_type, Certification.valid_until).where(
                        Certification.resource_id.in_(people_uuids), Certification.status == "valid"
                    )
                )
            ).all():
                if not valid_until or str(valid_until)[:10] >= d:
                    facts.valid_certs.setdefault(str(rid), set()).add(str(ctype))
            day_start = datetime.combine(day, time.min, tzinfo=UTC)
            day_end = day_start + timedelta(days=1)
            for rid, wtype in (
                await self.session.execute(
                    select(AvailabilityWindow.resource_id, AvailabilityWindow.window_type).where(
                        AvailabilityWindow.resource_id.in_(people_uuids),
                        AvailabilityWindow.window_type.in_(logic.ABSENCE_WINDOWS),
                        AvailabilityWindow.start_at < day_end,
                        AvailabilityWindow.end_at > day_start,
                    )
                )
            ).all():
                facts.absences[str(rid)] = str(wtype)
        return facts

    def _placement_out(self, p: DispatchPlacement, facts: logic.DayFacts, conflicts: list[logic.Conflict]) -> dict:
        kinds = sorted({c.kind for c in conflicts if str(p.id) in c.placement_ids})
        members: list[dict[str, str]] = []
        status_ = ""
        subtitle = ""
        if p.card_kind == "crew":
            crew = facts.crews.get(p.card_ref) or {}
            members = [
                {
                    "id": m,
                    "name": facts.label("worker", m),
                    "absent": facts.absences.get(m, ""),
                }
                for m in crew.get("member_ids") or []
            ]
            subtitle = str(len(members))
        eq = logic.placement_equipment_id({"card_kind": p.card_kind, "card_ref": p.card_ref}, facts)
        if eq:
            status_ = logic.unit_status(eq, facts, self._in_transit)
        elif p.card_kind == "worker" and facts.absences.get(p.card_ref):
            status_ = "absent"
        return {
            "id": p.id,
            "day": p.day,
            "card_kind": p.card_kind,
            "card_ref": p.card_ref,
            "location_id": p.location_id,
            "operator_ref": p.operator_ref,
            "start_time": p.start_time,
            "notes": p.notes,
            "source": p.source,
            "label": facts.label(p.card_kind, p.card_ref),
            "subtitle": subtitle,
            "status": status_,
            "members": members,
            "conflict_kinds": kinds,
        }

    # ── Board ───────────────────────────────────────────────────────────

    async def board(self, day: date, *, today: date | None = None) -> dict[str, Any]:
        """One day's board: columns, cards with status, conflicts and moves still to come."""
        applied = await self.apply_due_moves(today or _today()) if day <= (today or _today()) else 0
        placements = await self.repo.placements_on(day)
        facts = await self._facts(day, placements)
        moves_today = await self.repo.list_moves(start=day, end=day)
        self._in_transit = {
            logic.placement_equipment_id({"card_kind": m.card_kind, "card_ref": m.card_ref}, facts) or ""
            for m in moves_today
            if m.status != "cancelled"
        }
        conflicts = logic.detect_conflicts(facts)
        return {
            "day": day,
            "locations": await self.repo.list_locations(),
            "placements": [self._placement_out(p, facts, conflicts) for p in placements],
            "conflicts": [c.as_dict() for c in conflicts],
            "pending_moves": [m for m in moves_today if m.status == "pending"],
            "applied_moves": applied,
        }

    async def week(self, start: date) -> dict[str, Any]:
        """Seven days from ``start``, cards and conflict counts per day."""
        days = []
        for i in range(7):
            d = start + timedelta(days=i)
            placements = await self.repo.placements_on(d)
            facts = await self._facts(d, placements)
            self._in_transit = set()
            conflicts = logic.detect_conflicts(facts)
            days.append(
                {
                    "day": d,
                    "placements": [self._placement_out(p, facts, conflicts) for p in placements],
                    "conflict_count": len(conflicts),
                }
            )
        return {"start": start, "locations": await self.repo.list_locations(), "days": days}

    async def conflicts(self, day: date) -> list[logic.Conflict]:
        placements = await self.repo.placements_on(day)
        return logic.detect_conflicts(await self._facts(day, placements))

    # ── Writes ──────────────────────────────────────────────────────────

    async def _location(self, location_id: uuid.UUID) -> DispatchLocation:
        loc = await self.repo.get_location(location_id)
        if loc is None or not loc.is_active:
            raise _not_found("Location")
        return loc

    async def place(self, data: PlaceRequest, user_id: str | None) -> list[DispatchPlacement]:
        """Put cards on a column; a card already on that column that day is left as it is."""
        await self._location(data.location_id)
        existing = {
            (p.card_kind, p.card_ref)
            for p in await self.repo.placements_on(data.day)
            if p.location_id == data.location_id
        }
        created: list[DispatchPlacement] = []
        for card in data.cards:
            if (card.card_kind, card.card_ref) in existing:
                continue
            existing.add((card.card_kind, card.card_ref))
            p = DispatchPlacement(
                day=data.day,
                card_kind=card.card_kind,
                card_ref=card.card_ref,
                location_id=data.location_id,
                operator_ref=data.operator_ref,
                start_time=data.start_time,
                notes=data.notes,
                source="manual",
                created_by=user_id,
            )
            await self.repo.add(p)
            created.append(p)
        return created

    async def move(self, data: MoveRequest) -> list[DispatchPlacement]:
        """Drag to another column. If the card is already there that day, the duplicate is dropped."""
        await self._location(data.to_location_id)
        moved = await self.repo.placements_by_ids(list(data.placement_ids))
        out: list[DispatchPlacement] = []
        for p in moved:
            if p.location_id == data.to_location_id:
                out.append(p)
                continue
            same_day = await self.repo.placements_on(p.day)
            if any(
                o.location_id == data.to_location_id and o.card_kind == p.card_kind and o.card_ref == p.card_ref
                for o in same_day
            ):
                await self.repo.delete_placements([p.id])
                continue
            p.location_id = data.to_location_id
            out.append(p)
        await self.session.flush()
        return out

    async def update_placement(self, placement_id: uuid.UUID, data: PlacementUpdate) -> DispatchPlacement:
        rows = await self.repo.placements_by_ids([placement_id])
        if not rows:
            raise _not_found("Placement")
        p = rows[0]
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(p, key, value if value is not None or key == "operator_ref" else getattr(p, key))
        await self.session.flush()
        return p

    async def remove(self, ids: list[uuid.UUID]) -> int:
        return await self.repo.delete_placements(ids)

    async def copy_day(self, data: CopyDayRequest, user_id: str | None) -> int:
        """Repeat a day's board on another day. Without ``replace`` existing cards stay."""
        if data.from_day == data.to_day:
            raise HTTPException(status_code=422, detail="Pick two different days")
        source = await self.repo.placements_on(data.from_day)
        target = await self.repo.placements_on(data.to_day)
        if data.replace:
            await self.repo.delete_placements([p.id for p in target])
            target = []
        have = {(p.card_kind, p.card_ref, p.location_id) for p in target}
        active = {loc.id for loc in await self.repo.list_locations()}
        n = 0
        for p in source:
            key = (p.card_kind, p.card_ref, p.location_id)
            if key in have or p.location_id not in active:
                continue
            await self.repo.add(
                DispatchPlacement(
                    day=data.to_day,
                    card_kind=p.card_kind,
                    card_ref=p.card_ref,
                    location_id=p.location_id,
                    operator_ref=p.operator_ref,
                    start_time=p.start_time,
                    notes=p.notes,
                    source="copied",
                    created_by=user_id,
                )
            )
            have.add(key)
            n += 1
        return n

    # ── Scheduled moves ─────────────────────────────────────────────────

    async def schedule_move(self, data: ScheduleMoveRequest, user_id: str | None) -> DispatchScheduledMove:
        await self._location(data.to_location_id)
        if data.effective_date < _today():
            raise HTTPException(status_code=422, detail="A move can only be booked for today or later")
        move = DispatchScheduledMove(
            card_kind=data.card_kind,
            card_ref=data.card_ref,
            to_location_id=data.to_location_id,
            effective_date=data.effective_date,
            start_time=data.start_time,
            notes=data.notes,
            status="pending",
            created_by=user_id,
        )
        await self.repo.add(move)
        return move

    async def cancel_move(self, move_id: uuid.UUID) -> DispatchScheduledMove:
        move = await self.repo.get_move(move_id)
        if move is None:
            raise _not_found("Move")
        if move.status != "pending":
            raise HTTPException(status_code=409, detail="Only a pending move can be cancelled")
        move.status = "cancelled"
        await self.session.flush()
        return move

    async def apply_due_moves(self, today: date) -> int:
        """Apply every pending move dated today or earlier on its own date. Idempotent."""
        pending = await self.repo.list_moves(status="pending", end=today)
        due = logic.due_moves(
            [
                {"id": m.id, "status": m.status, "effective_date": m.effective_date, "created_at": m.created_at}
                for m in pending
            ],
            today,
        )
        by_id = {m.id: m for m in pending}
        for row in due:
            m = by_id[row["id"]]
            day_rows = await self.repo.placements_on(m.effective_date)
            remove, create = logic.plan_move(
                [
                    {"id": p.id, "card_kind": p.card_kind, "card_ref": p.card_ref, "location_id": str(p.location_id)}
                    for p in day_rows
                ],
                m.card_kind,
                m.card_ref,
                str(m.to_location_id),
            )
            await self.repo.delete_placements([uuid.UUID(i) for i in remove])
            if create:
                await self.repo.add(
                    DispatchPlacement(
                        day=m.effective_date,
                        card_kind=m.card_kind,
                        card_ref=m.card_ref,
                        location_id=m.to_location_id,
                        start_time=m.start_time,
                        notes=m.notes,
                        source="scheduled",
                        created_by=m.created_by,
                    )
                )
            m.status = "applied"
            m.applied_at = datetime.now(UTC)
        await self.session.flush()
        if due:
            logger.info("dispatch: applied %d scheduled move(s) up to %s", len(due), today)
        return len(due)

    # ── Daily plan, PDF, share ──────────────────────────────────────────

    async def daily_plan(self, day: date) -> list[dict[str, Any]]:
        """Per foreman: who, which machine, where, start time, notes.

        Each location's foreman is the foreman of a crew placed there; cards at a location
        with no crew foreman go under an empty foreman so nothing drops off the plan.
        """
        await self.apply_due_moves(min(day, _today()))
        placements = await self.repo.placements_on(day)
        facts = await self._facts(day, placements)
        locs = {loc.id: loc for loc in await self.repo.list_locations(include_inactive=True)}
        crews = {str(c.id): c for c in await self.repo.crews_by_ids({p.card_ref for p in placements})}
        foreman_of_loc: dict[uuid.UUID, DispatchCrew] = {}
        for p in placements:
            c = crews.get(p.card_ref) if p.card_kind == "crew" else None
            if c and (c.foreman_user_id or c.foreman_resource_id) and p.location_id not in foreman_of_loc:
                foreman_of_loc[p.location_id] = c
        plans: dict[str, dict[str, Any]] = {}
        for p in sorted(placements, key=lambda x: (x.start_time, str(x.location_id))):
            crew = foreman_of_loc.get(p.location_id)
            foreman = ""
            if crew is not None:
                foreman = facts.label("worker", crew.foreman_resource_id) if crew.foreman_resource_id else crew.name
            key = str(crew.id) if crew else ""
            plan = plans.setdefault(
                key, {"foreman": foreman, "foreman_user_id": crew.foreman_user_id if crew else None, "lines": []}
            )
            who = facts.label(p.card_kind, p.card_ref)
            if p.card_kind == "crew":
                members = facts.crews.get(p.card_ref, {}).get("member_ids") or []
                who = f"{who}: " + ", ".join(facts.label("worker", m) for m in members)
            loc = locs.get(p.location_id)
            plan["lines"].append(
                {
                    "location": loc.name if loc else "",
                    "location_id": p.location_id,
                    "card_kind": p.card_kind,
                    "who_or_what": who,
                    "operator": facts.label("worker", p.operator_ref) if p.operator_ref else "",
                    "start_time": p.start_time,
                    "notes": p.notes,
                }
            )
        return sorted(plans.values(), key=lambda x: (x["foreman"] == "", x["foreman"]))

    async def daily_plan_pdf(self, day: date) -> bytes:
        from app.modules.dispatch.pdf import render_daily_plan

        return render_daily_plan(day, await self.daily_plan(day))

    async def share_plan(self, day: date) -> dict[str, Any]:
        """Send each foreman with a platform account a notification that links the plan."""
        plans = await self.daily_plan(day)
        notified = 0
        without: list[str] = []
        try:
            from app.modules.notifications.service import NotificationService
        except ImportError:  # notifications module not installed
            NotificationService = None  # type: ignore[assignment]  # noqa: N806
        for plan in plans:
            uid = plan.get("foreman_user_id")
            if not uid or NotificationService is None:
                if plan["foreman"]:
                    without.append(plan["foreman"])
                continue
            await NotificationService(self.session).create(
                user_id=uid,
                notification_type="info",
                title_key="dispatch.notify.plan_title",
                entity_type="dispatch_plan",
                entity_id=day.isoformat(),
                body_key="dispatch.notify.plan_body",
                body_context={"day": day.isoformat(), "lines": len(plan["lines"])},
                action_url=f"/dispatch?day={day.isoformat()}&plan=1",
            )
            notified += 1
        return {"day": day, "notified": notified, "without_user": without}

    # ── Field link ──────────────────────────────────────────────────────

    async def prefill_timesheet(self, data: PrefillRequest, user_id: str | None) -> dict[str, Any]:
        """Draft (or top up) the site's field timesheet with the dispatched people and machines."""
        from app.modules.field_time.models import FieldTimesheet
        from app.modules.field_time.schemas import FieldTimesheetCreate, FieldTimesheetLineCreate
        from app.modules.field_time.service import FieldTimeService

        loc = await self._location(data.location_id)
        if loc.project_id is None:
            raise HTTPException(status_code=422, detail="Only a project column has a site timesheet")
        await self.apply_due_moves(min(data.day, _today()))
        placements = [p for p in await self.repo.placements_on(data.day) if p.location_id == loc.id]
        facts = await self._facts(data.day, placements)
        existing = (
            await self.session.execute(
                select(FieldTimesheet).where(
                    FieldTimesheet.project_id == loc.project_id,
                    FieldTimesheet.date == data.day,
                    FieldTimesheet.status == "draft",
                )
            )
        ).scalars()
        sheet = next((s for s in existing if (s.metadata_ or {}).get("source") == "dispatch"), None)
        have_r = {str(ln.resource_id) for ln in (sheet.lines if sheet else []) if ln.resource_id}
        have_e = {str(ln.equipment_id) for ln in (sheet.lines if sheet else []) if ln.equipment_id}
        lines = logic.timesheet_lines(
            facts.placements,
            facts.crews,
            facts.rentals,
            hours=Decimal(data.hours),
            existing_resources=have_r,
            existing_equipment=have_e,
        )
        creates = [
            FieldTimesheetLineCreate(
                resource_id=ln.get("resource_id"),
                equipment_id=ln.get("equipment_id"),
                hours=ln["hours"],
                note=ln.get("note"),
            )
            for ln in lines
        ]
        svc = FieldTimeService(self.session)
        if sheet is None:
            sheet = await svc.create_timesheet(
                FieldTimesheetCreate(
                    project_id=loc.project_id,
                    date=data.day,
                    note=f"Prefilled from the dispatch board for {loc.name}",
                    metadata={"source": "dispatch", "dispatch_location_id": str(loc.id)},
                    lines=creates,
                ),
                user_id,
            )
            return {"timesheet_id": sheet.id, "reference": sheet.reference, "created": True, "lines_added": len(lines)}
        for c in creates:
            await svc.add_line(sheet.id, c)
        return {"timesheet_id": sheet.id, "reference": sheet.reference, "created": False, "lines_added": len(lines)}

    # ── Utilisation ─────────────────────────────────────────────────────

    async def utilisation(self, start: date, end: date, *, limit: int = 200, offset: int = 0) -> list[dict]:
        """Equipment and rentals: working days on a project vs idle in the range."""
        from app.modules.equipment.models import Equipment, EquipmentRental

        if (end - start).days > 92:
            raise HTTPException(status_code=422, detail="Pick a range of at most three months")
        locs = {loc.id: loc.kind for loc in await self.repo.list_locations(include_inactive=True)}
        rows = [p for p in await self.repo.placements_between(start, end) if p.card_kind in ("equipment", "rental")]
        rentals: dict[str, str] = {}
        rental_ids = [uuid.UUID(p.card_ref) for p in rows if p.card_kind == "rental" and _is_uuid(p.card_ref)]
        if rental_ids:
            rentals = {
                str(r): str(e)
                for r, e in (
                    await self.session.execute(
                        select(EquipmentRental.id, EquipmentRental.equipment_id).where(
                            EquipmentRental.id.in_(rental_ids)
                        )
                    )
                ).all()
            }
        flat = [
            {
                "day": p.day,
                "location_kind": locs.get(p.location_id, ""),
                "unit_ref": rentals.get(p.card_ref, p.card_ref) if p.card_kind == "rental" else p.card_ref,
            }
            for p in rows
        ]
        units_stmt = (
            select(Equipment.id, Equipment.code, Equipment.name, Equipment.ownership)
            .where(Equipment.status != "decommissioned")
            .order_by(Equipment.code)
            .limit(limit)
            .offset(offset)
        )
        units = (await self.session.execute(units_stmt)).all()
        meta = {str(i): (f"{c} {n}", "rental" if o in ("rented", "leased") else "equipment") for i, c, n, o in units}
        out = logic.utilisation(flat, list(meta), start, end)
        for row in out:
            row["label"], row["card_kind"] = meta[row["unit_ref"]]
        return out

    # ── Validation and preferences ──────────────────────────────────────

    async def validate_day(self, day: date) -> dict[str, Any]:
        from app.core.validation.engine import validation_engine
        from app.modules.dispatch.validators import DISPATCH_RULE_SET

        conflicts = await self.conflicts(day)
        report = await validation_engine.validate(
            data={"day": day.isoformat(), "conflicts": [c.as_dict() for c in conflicts]},
            rule_sets=[DISPATCH_RULE_SET],
            target_type="dispatch_day",
            target_id=day.isoformat(),
        )
        failed = [r for r in report.results if not r.passed]
        return {
            "day": day,
            "status": "errors" if report.errors else "warnings" if report.warnings else "passed",
            "checked": len(report.results),
            "results": [
                {
                    "rule_id": r.rule_id,
                    "severity": str(r.severity),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details,
                }
                for r in failed
            ],
        }

    async def get_pref(self, user_id: str) -> ViewPref:
        pref = await self.repo.get_pref(uuid.UUID(str(user_id))) if _is_uuid(user_id) else None
        if pref is None:
            return ViewPref()
        return ViewPref(card_density=pref.card_density, settings=dict(pref.settings or {}))

    async def set_pref(self, user_id: str, data: ViewPref) -> ViewPref:
        if not _is_uuid(user_id):
            raise HTTPException(status_code=401, detail="Sign in to save a preference")
        uid = uuid.UUID(str(user_id))
        pref = await self.repo.get_pref(uid)
        if pref is None:
            pref = DispatchViewPref(user_id=uid, card_density=data.card_density, settings=data.settings)
            await self.repo.add(pref)
        else:
            pref.card_density = data.card_density
            pref.settings = data.settings
            await self.session.flush()
        return data
