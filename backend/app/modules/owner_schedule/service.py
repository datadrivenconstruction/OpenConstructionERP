# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule service: profiles, import into a BOQ, addenda, pricing status and export.

Each owner pay item becomes one top-level BOQ position carrying the owner's item
number, text, unit and quantity under ``metadata["owner_ref"]``. The estimator's
own breakdown goes below that position and is free; the position's unit rate
(or, when it has none, its children's total over the quantity) is the price.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.owner_schedule import engine
from app.modules.owner_schedule.models import OwnerSchedule, OwnerScheduleItem, OwnerScheduleProfile
from app.modules.owner_schedule.profile import ScheduleProfile, pack_profiles, platform_profiles
from app.modules.owner_schedule.repository import OwnerScheduleRepository
from app.modules.owner_schedule.validators import evaluate

SOURCE = "owner_schedule"
SECTION_UNITS = ("", "section")


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _bad(detail: str, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(code, detail=detail)


class OwnerScheduleService:
    """Owner bid schedule round trip over one BOQ."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = OwnerScheduleRepository(session)

    # -- profiles ----------------------------------------------------------

    async def profiles(self) -> list[ScheduleProfile]:
        out = platform_profiles() + pack_profiles()
        for row in await self.repo.user_profiles():
            try:
                out.append(ScheduleProfile.model_validate({**row.definition, "key": row.key, "source": "user"}))
            except ValueError:
                continue
        return out

    async def profile(self, key: str) -> ScheduleProfile:
        for p in await self.profiles():
            if p.key == key:
                return p
        raise _bad(f"unknown profile {key}", status.HTTP_404_NOT_FOUND)

    async def save_profile(self, definition: dict[str, Any], user_id: str | None) -> ScheduleProfile:
        prof = ScheduleProfile.model_validate({**definition, "source": "user"})
        if prof.key in {p.key for p in platform_profiles() + pack_profiles()}:
            raise _bad("a platform or pack profile already uses this key", status.HTTP_409_CONFLICT)
        row = await self.repo.user_profile(prof.key)
        data = prof.model_dump(mode="json")
        if row is None:
            self.session.add(OwnerScheduleProfile(key=prof.key, name=prof.name, definition=data, created_by=user_id))
        else:
            row.name, row.definition = prof.name, data
        await self.session.flush()
        return prof

    async def detect(self, content: bytes, file_name: str) -> list[dict[str, Any]]:
        return engine.detect(content, file_name, await self.profiles())

    async def preview(self, content: bytes, file_name: str, profile_key: str) -> engine.ParseResult:
        prof = await self.profile(profile_key)
        try:
            return engine.parse(content, file_name, prof)
        except engine.ScheduleFileError as exc:
            raise _bad(str(exc)) from exc

    # -- import ------------------------------------------------------------

    async def _boq(self, boq_id: uuid.UUID) -> BOQ:
        boq = await self.session.get(BOQ, boq_id)
        if boq is None:
            raise _bad("BOQ not found", status.HTTP_404_NOT_FOUND)
        return boq

    async def schedule(self, boq_id: uuid.UUID) -> OwnerSchedule:
        sched = await self.repo.by_boq(boq_id)
        if sched is None:
            raise _bad("no owner schedule on this BOQ", status.HTTP_404_NOT_FOUND)
        return sched

    async def _positions(self, boq_id: uuid.UUID) -> list[Position]:
        rows = await self.session.execute(select(Position).where(Position.boq_id == boq_id))
        return list(rows.scalars())

    async def _next_sort(self, boq_id: uuid.UUID) -> int:
        value = await self.session.scalar(select(func.max(Position.sort_order)).where(Position.boq_id == boq_id))
        return int(value or 0) + 1

    def _owner_ref(self, sched_id: uuid.UUID, ln: engine.ScheduleLine) -> dict[str, Any]:
        return {
            "schedule_id": str(sched_id),
            "item_no": ln.item_no,
            "description": ln.description,
            "unit": ln.unit,
            "quantity": None if ln.quantity is None else str(ln.quantity),
        }

    def _new_position(
        self, boq_id: uuid.UUID, parent: uuid.UUID | None, ln: engine.ScheduleLine, ref: dict, sort: int
    ) -> Position:
        qty = "0" if ln.quantity is None else format(ln.quantity, "f")
        return Position(
            boq_id=boq_id,
            parent_id=parent,
            ordinal=ln.item_no[:50],
            description=ln.description or ln.item_no,
            unit="section" if ln.is_section else (ln.unit or "")[:20],
            quantity=qty,
            unit_rate="0",
            total="0",
            classification={},
            source=SOURCE,
            confidence=None,
            cad_element_ids=[],
            metadata_={"owner_ref": ref},
            sort_order=sort,
        )

    async def import_schedule(
        self, boq_id: uuid.UUID, content: bytes, file_name: str, profile_key: str, user_id: str | None
    ) -> dict[str, Any]:
        boq = await self._boq(boq_id)
        if await self.repo.by_boq(boq_id) is not None:
            raise _bad("this BOQ already has an owner schedule; upload a revision as an addendum", 409)
        prof = await self.profile(profile_key)
        res = await self.preview(content, file_name, profile_key)
        errors = [i for i in res.issues if i["severity"] == "error"]
        if errors:
            raise _bad(f"the schedule has {len(errors)} blocking issue(s); fix them or pick another profile")
        sched = OwnerSchedule(
            project_id=boq.project_id,
            boq_id=boq_id,
            profile_key=prof.key,
            profile=prof.model_dump(mode="json"),
            file_name=file_name[:255],
            file_content=content,
            revision=0,
            created_by=user_id,
        )
        self.session.add(sched)
        await self.session.flush()
        existing = {p.ordinal.strip(): p for p in await self._positions(boq_id)}
        sort = await self._next_sort(boq_id)
        created = linked = 0
        section: uuid.UUID | None = None
        for ln in res.lines:
            ref = self._owner_ref(sched.id, ln)
            pos = existing.get(ln.item_no)
            if pos is None:
                pos = self._new_position(boq_id, None if ln.is_section else section, ln, ref, sort)
                sort += 1
                self.session.add(pos)
                await self.session.flush()
                created += 1
            else:
                pos.metadata_ = {**(pos.metadata_ or {}), "owner_ref": ref}
                linked += 1
            if ln.is_section:
                section = pos.id
            self.session.add(self._item(sched.id, ln, pos.id, 0))
        await self.session.flush()
        return {
            "schedule_id": sched.id,
            "created_positions": created,
            "linked_positions": linked,
            "item_count": len([ln for ln in res.lines if not ln.is_section]),
        }

    @staticmethod
    def _item(sched_id: uuid.UUID, ln: engine.ScheduleLine, pos_id: uuid.UUID | None, rev: int) -> OwnerScheduleItem:
        return OwnerScheduleItem(
            schedule_id=sched_id,
            row_index=ln.row,
            item_no=ln.item_no[:80],
            description=ln.description,
            unit=ln.unit[:40],
            quantity=ln.quantity,
            is_section=ln.is_section,
            is_alternate=ln.is_alternate,
            is_lump_sum=ln.is_lump_sum,
            revision=rev,
            position_id=pos_id,
        )

    # -- addenda -----------------------------------------------------------

    @staticmethod
    def _item_dict(it: OwnerScheduleItem) -> dict[str, Any]:
        return {
            "item_no": it.item_no,
            "description": it.description,
            "unit": it.unit,
            "quantity": None if it.quantity is None else str(it.quantity.normalize()),
            "is_section": it.is_section,
            "removed": it.removed,
        }

    async def addendum_preview(self, boq_id: uuid.UUID, content: bytes, file_name: str) -> dict[str, Any]:
        sched = await self.schedule(boq_id)
        prof = ScheduleProfile.model_validate(sched.profile)
        try:
            res = engine.parse(content, file_name, prof)
        except engine.ScheduleFileError as exc:
            raise _bad(str(exc)) from exc
        current = [self._item_dict(i) for i in await self.repo.items(sched.id)]
        return {"file_name": file_name, "changes": engine.diff_items(current, res.lines), "issues": res.issues}

    async def apply_addendum(
        self, boq_id: uuid.UUID, content: bytes, file_name: str, item_nos: list[str] | None
    ) -> dict[str, Any]:
        """Apply the chosen changes (all when ``item_nos`` is None) and make the revised file the template."""
        sched = await self.schedule(boq_id)
        prof = ScheduleProfile.model_validate(sched.profile)
        res = engine.parse(content, file_name, prof)
        if [i for i in res.issues if i["severity"] == "error"]:
            raise _bad("the revised schedule has blocking issues")
        items = {i.item_no: i for i in await self.repo.items(sched.id)}
        changes = engine.diff_items([self._item_dict(i) for i in items.values()], res.lines)
        chosen = {c["item_no"] for c in changes} if item_nos is None else set(item_nos)
        new_lines = {ln.item_no: ln for ln in res.lines}
        rev = sched.revision + 1
        positions = {p.id: p for p in await self._positions(boq_id)}
        sort = await self._next_sort(boq_id)
        applied = 0
        for c in changes:
            if c["item_no"] not in chosen:
                continue
            applied += 1
            no = c["item_no"]
            if c["kind"] == "removed":
                items[no].removed = True
                items[no].revision = rev
                continue
            ln = new_lines[no]
            ref = self._owner_ref(sched.id, ln)
            if c["kind"] == "added":
                pos = self._new_position(boq_id, None, ln, ref, sort)
                sort += 1
                self.session.add(pos)
                await self.session.flush()
                self.session.add(self._item(sched.id, ln, pos.id, rev))
                continue
            it = items[no]
            it.description, it.unit, it.quantity, it.revision = ln.description, ln.unit[:40], ln.quantity, rev
            it.is_lump_sum, it.is_alternate = ln.is_lump_sum, ln.is_alternate
            pos = positions.get(it.position_id) if it.position_id else None
            if pos is not None:
                pos.metadata_ = {**(pos.metadata_ or {}), "owner_ref": ref}
                pos.unit = (ln.unit or pos.unit)[:20]
                if ln.quantity is not None:
                    pos.quantity = format(ln.quantity, "f")
                    pos.total = format(_dec(pos.unit_rate) * ln.quantity, "f")
        for no, it in items.items():
            if no in new_lines:
                it.row_index = new_lines[no].row
        sched.file_content, sched.file_name, sched.revision = content, file_name[:255], rev
        await self.session.flush()
        return {"revision": rev, "applied": applied}

    # -- pricing, status, export --------------------------------------------

    async def _prices(self, items: list[OwnerScheduleItem], boq_id: uuid.UUID) -> dict[str, Decimal | None]:
        positions = await self._positions(boq_id)
        by_id = {p.id: p for p in positions}
        child_total: dict[uuid.UUID, Decimal] = {}
        for p in positions:
            if p.parent_id is not None:
                child_total[p.parent_id] = child_total.get(p.parent_id, Decimal(0)) + _dec(p.total)
        out: dict[str, Decimal | None] = {}
        for it in items:
            pos = by_id.get(it.position_id) if it.position_id else None
            if it.is_section or it.removed or pos is None:
                continue
            rate = _dec(pos.unit_rate)
            if rate == 0 and pos.id in child_total:
                qty = it.quantity or Decimal(1)
                rate = child_total[pos.id] / qty if qty else Decimal(0)
            out[it.item_no] = rate if rate > 0 else None
        return out

    async def _priced(
        self, sched: OwnerSchedule
    ) -> tuple[ScheduleProfile, list[OwnerScheduleItem], list, Decimal, Decimal]:
        prof = ScheduleProfile.model_validate(sched.profile)
        items = await self.repo.items(sched.id)
        live = [i for i in items if not i.removed]
        lines = [
            engine.ScheduleLine(
                row=i.row_index,
                item_no=i.item_no,
                description=i.description,
                unit=i.unit,
                quantity=i.quantity,
                is_section=i.is_section,
                is_alternate=i.is_alternate,
                is_lump_sum=i.is_lump_sum,
            )
            for i in live
        ]
        priced, base, alts = engine.price_lines(lines, await self._prices(live, sched.boq_id), prof)
        return prof, items, priced, base, alts

    async def validation_snapshot(self, boq_id: uuid.UUID) -> dict[str, Any]:
        sched = await self.schedule(boq_id)
        prof, items, priced, base, _ = await self._priced(sched)
        by_no = {p.item_no: p for p in priced}
        positions = await self._positions(boq_id)
        by_id = {p.id: p for p in positions}
        linked = {i.position_id for i in items if i.position_id and not i.removed}
        rows = []
        for it in items:
            if it.is_section or it.removed:
                continue
            pl = by_no.get(it.item_no)
            pos = by_id.get(it.position_id) if it.position_id else None
            rows.append(
                {
                    "item_no": it.item_no,
                    "unit": it.unit,
                    "quantity": None if it.quantity is None else str(it.quantity),
                    "is_alternate": it.is_alternate,
                    "is_lump_sum": it.is_lump_sum,
                    "unit_price": None if pl is None or pl.unit_price is None else str(pl.unit_price),
                    "amount": None if pl is None or pl.amount is None else str(pl.amount),
                    "position_unit": None if pos is None else pos.unit,
                    "position_quantity": None if pos is None else pos.quantity,
                }
            )
        extras = [
            {"ordinal": p.ordinal, "position_id": str(p.id)}
            for p in positions
            if p.parent_id is None and p.id not in linked and p.unit not in SECTION_UNITS
        ]
        return {
            "items": rows,
            "extra_positions": extras,
            "rounding": prof.rounding.model_dump(),
            "alternates_required": prof.alternates_required,
            "total": str(base),
        }

    async def findings(self, boq_id: uuid.UUID) -> list[dict[str, Any]]:
        snap = await self.validation_snapshot(boq_id)
        return [
            {"rule_id": r.rule_id, "severity": str(r.severity.value), "message": r.message, "item_no": r.element_ref}
            for r in await evaluate(snap, target_id=str(boq_id))
        ]

    async def status_of(self, boq_id: uuid.UUID) -> dict[str, Any]:
        sched = await self.schedule(boq_id)
        prof, items, priced, base, alts = await self._priced(sched)
        by_no = {p.item_no: p for p in priced}
        out_items = []
        for it in items:
            pl = by_no.get(it.item_no)
            out_items.append(
                {
                    "id": it.id,
                    "item_no": it.item_no,
                    "description": it.description,
                    "unit": it.unit,
                    "quantity": None if it.quantity is None else format(it.quantity.normalize(), "f"),
                    "is_section": it.is_section,
                    "is_alternate": it.is_alternate,
                    "is_lump_sum": it.is_lump_sum,
                    "removed": it.removed,
                    "position_id": it.position_id,
                    "unit_price": None if pl is None or pl.unit_price is None else str(pl.unit_price),
                    "amount": None if pl is None or pl.amount is None else str(pl.amount),
                }
            )
        countable = [p for p in priced if not p.is_alternate]
        return {
            "id": sched.id,
            "boq_id": sched.boq_id,
            "profile_key": sched.profile_key,
            "profile_name": prof.name,
            "file_name": sched.file_name,
            "revision": sched.revision,
            "item_count": len(countable),
            "priced_count": len([p for p in countable if p.unit_price is not None]),
            "total": str(base),
            "alternates_total": str(alts),
            "items": out_items,
            "findings": await self.findings(boq_id),
        }

    async def export(self, boq_id: uuid.UUID) -> tuple[bytes, str, dict[str, Any]]:
        """Write the priced schedule into the owner's latest file and return it with a check report."""
        sched = await self.schedule(boq_id)
        prof, _, priced, base, alts = await self._priced(sched)
        # Rows come from the template itself, so an addendum file maps by item number.
        res = engine.parse(sched.file_content, sched.file_name, prof)
        rows = {ln.item_no: ln.row for ln in res.lines}
        for p in priced:
            p.row = rows.get(p.item_no, 0)
        content, writes = engine.write_back(
            sched.file_content, sched.file_name, prof, [p for p in priced if p.row], base
        )
        line_sum = sum((p.amount for p in priced if p.amount is not None and not p.is_alternate), Decimal(0))
        report = {
            "file_name": sched.file_name,
            "total": str(base),
            "alternates_total": str(alts),
            "line_sum": str(line_sum),
            "writes": writes,
            "findings": await self.findings(boq_id),
        }
        return content, sched.file_name, report

    async def check_report(self, boq_id: uuid.UUID) -> dict[str, Any]:
        _, _, report = await self.export(boq_id)
        return report
