# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey business logic.

The actual of a unit is the cut of a Volumes calculation (start of the period
against its end), never a typed number. The computer suggests, a person
confirms: the volume is confirmed through the surfaces_volumes workflow, and
only a confirmed volume can be added to the progress claim.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mine_survey import calc
from app.modules.mine_survey.models import MinePeriod, MinePeriodEntry, MineUnit
from app.modules.mine_survey.repository import MineRepository
from app.modules.mine_survey.schemas import (
    ActualOut,
    AddToClaim,
    ClaimResult,
    ComputeActual,
    ConfirmActual,
    EntryCreate,
    EntryOut,
    EntryUpdate,
    Finding,
    PeriodCreate,
    PeriodDetail,
    PeriodOut,
    PeriodUpdate,
    PlanImport,
    PlanImportResult,
    Totals,
    TruckLoadsImport,
    UnitCreate,
    UnitOut,
    UnitUpdate,
)
from app.modules.mine_survey.validators import MINE_RULE_SET
from app.modules.surfaces_volumes.models import SurveyVolume
from app.modules.surfaces_volumes.service import VolumesService

logger = logging.getLogger(__name__)


def _err(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _bad(detail: str) -> HTTPException:
    return _err(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _q(value: float | Decimal | None, places: str) -> Decimal | None:
    return None if value is None else calc.dec(value).quantize(Decimal(places), ROUND_HALF_UP)


def _next_code(codes: list[str]) -> str:
    top = 0
    for c in codes:
        tail = c[3:] if c.startswith("MU-") else ""
        if tail.isdigit():
            top = max(top, int(tail))
    return f"MU-{top + 1:03d}"


def _month(label: str) -> tuple[date, date]:
    year, month = int(label[:4]), int(label[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


class MineService:
    """Stateless operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MineRepository(session)
        self.volumes = VolumesService(session)

    async def _audit(self, action: str, entity_type: str, entity_id: uuid.UUID, user_id: str, details: dict) -> None:
        try:
            from app.core.audit import audit_log  # noqa: PLC0415

            uid = _uuid(user_id)
            await audit_log(
                self.session,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                user_id=str(uid) if uid else None,
                details=details,
            )
        except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
            logger.exception("mine_survey: audit entry for %s failed", entity_id)

    # ── Units ──────────────────────────────────────────────────────────────

    def _unit_out(self, u: MineUnit, count: int = 0) -> UnitOut:
        return UnitOut(
            id=u.id,
            project_id=u.project_id,
            code=u.code,
            name=u.name,
            unit_type=u.unit_type,
            underground=u.unit_type in calc.UNDERGROUND,
            density_t_m3=_f(u.density_t_m3),
            entry_count=count,
        )

    async def list_units(self, project_id: uuid.UUID) -> list[UnitOut]:
        counts = await self.repo.entry_counts_by_unit(project_id)
        return [self._unit_out(u, counts.get(u.id, 0)) for u in await self.repo.list_units(project_id)]

    async def get_unit(self, unit_id: uuid.UUID) -> MineUnit:
        u = await self.repo.get_unit(unit_id)
        if u is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Unit not found")
        return u

    async def create_unit(self, project_id: uuid.UUID, data: UnitCreate, user_id: str) -> UnitOut:
        if await self.repo.unit_by_name(project_id, data.name):
            raise _err(status.HTTP_409_CONFLICT, "A unit with this name already exists")
        u = MineUnit(
            project_id=project_id,
            code=_next_code(await self.repo.unit_codes(project_id)),
            name=data.name.strip(),
            unit_type=data.unit_type,
            density_t_m3=_q(data.density_t_m3, "0.0001"),
            note=data.note,
            created_by=_uuid(user_id),
        )
        await self.repo.add(u)
        return self._unit_out(u)

    async def update_unit(self, u: MineUnit, data: UnitUpdate) -> UnitOut:
        if data.name is not None and data.name.strip().lower() != u.name.lower():
            if await self.repo.unit_by_name(u.project_id, data.name):
                raise _err(status.HTTP_409_CONFLICT, "A unit with this name already exists")
            u.name = data.name.strip()
        if data.unit_type is not None:
            u.unit_type = data.unit_type
        if data.density_t_m3 is not None:
            u.density_t_m3 = _q(data.density_t_m3, "0.0001")  # type: ignore[assignment]
        if data.note is not None:
            u.note = data.note
        await self.session.flush()
        return self._unit_out(u, (await self.repo.entry_counts_by_unit(u.project_id)).get(u.id, 0))

    async def delete_unit(self, u: MineUnit) -> None:
        if (await self.repo.entry_counts_by_unit(u.project_id)).get(u.id, 0):
            raise _err(status.HTTP_409_CONFLICT, "The unit is used in a period: remove its lines first")
        await self.repo.delete(u)

    # ── Periods ────────────────────────────────────────────────────────────

    def _period_out(self, p: MinePeriod, count: int = 0) -> PeriodOut:
        return PeriodOut(
            id=p.id,
            project_id=p.project_id,
            label=p.label,
            period_start=p.period_start,
            period_end=p.period_end,
            band_lo_pct=_f(p.band_lo_pct),
            band_hi_pct=_f(p.band_hi_pct),
            truck_tolerance_pct=_f(p.truck_tolerance_pct),
            profile_label=p.profile_label,
            note=p.note,
            entry_count=count,
        )

    async def list_periods(self, project_id: uuid.UUID) -> list[PeriodOut]:
        counts = await self.repo.entry_counts_by_period(project_id)
        return [self._period_out(p, counts.get(p.id, 0)) for p in await self.repo.list_periods(project_id)]

    async def get_period(self, period_id: uuid.UUID) -> MinePeriod:
        p = await self.repo.get_period(period_id)
        if p is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Period not found")
        return p

    async def create_period(self, project_id: uuid.UUID, data: PeriodCreate, user_id: str) -> PeriodOut:
        if await self.repo.period_by_label(project_id, data.label):
            raise _err(status.HTTP_409_CONFLICT, "This period already exists")
        start, end = _month(data.label)
        p = MinePeriod(
            project_id=project_id,
            label=data.label,
            period_start=start,
            period_end=end,
            band_lo_pct=_q(data.band_lo_pct, "0.01"),
            band_hi_pct=_q(data.band_hi_pct, "0.01"),
            truck_tolerance_pct=_q(data.truck_tolerance_pct, "0.01"),
            profile_label=data.profile_label.strip(),
            note=data.note,
            created_by=_uuid(user_id),
        )
        await self.repo.add(p)
        return self._period_out(p)

    async def update_period(self, p: MinePeriod, data: PeriodUpdate) -> PeriodOut:
        sent = data.model_fields_set
        if "band_lo_pct" in sent or "band_hi_pct" in sent:
            lo = data.band_lo_pct if "band_lo_pct" in sent else _f(p.band_lo_pct)
            hi = data.band_hi_pct if "band_hi_pct" in sent else _f(p.band_hi_pct)
            if (lo is None) != (hi is None) or (lo is not None and hi is not None and lo > hi):
                raise _bad("Set both ends of the compliance band, lower end first, or neither")
            p.band_lo_pct, p.band_hi_pct = _q(lo, "0.01"), _q(hi, "0.01")  # type: ignore[assignment]
        if "truck_tolerance_pct" in sent:
            p.truck_tolerance_pct = _q(data.truck_tolerance_pct, "0.01")  # type: ignore[assignment]
        if data.profile_label is not None:
            p.profile_label = data.profile_label.strip()
        if data.note is not None:
            p.note = data.note
        await self.session.flush()
        return self._period_out(p, len(await self.repo.entries_of(p.id)))

    async def delete_period(self, p: MinePeriod) -> None:
        for e in await self.repo.entries_of(p.id):
            if e.claim_entry_id:
                raise _err(status.HTTP_409_CONFLICT, "A line of this period is on a progress claim")
        await self.repo.delete(p)

    # ── Entries: output ────────────────────────────────────────────────────

    async def _volume_of(self, e: MinePeriodEntry) -> SurveyVolume | None:
        if e.actual_volume_id is None:
            return None
        return await self.session.get(SurveyVolume, e.actual_volume_id)

    def _numbers(self, e: MinePeriodEntry, v: SurveyVolume | None) -> dict[str, Decimal | None]:
        actual = v.cut_m3 if v is not None else None
        survey_t = calc.survey_tonnes(actual, e.density_t_m3)
        return {
            "actual": actual,
            "compliance": calc.compliance_pct(actual, e.plan_m3),
            "survey_t": survey_t,
            "truck_factor": calc.truck_factor_pct(e.truck_t, survey_t),
        }

    async def findings(self, e: MinePeriodEntry, p: MinePeriod, unit: MineUnit, locale: str = "en") -> list[Finding]:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        n = self._numbers(e, await self._volume_of(e))
        report = await validation_engine.validate(
            data={
                "entry": {
                    "unit": unit.name,
                    "compliance_pct": _f(n["compliance"]),
                    "band_lo": _f(p.band_lo_pct),
                    "band_hi": _f(p.band_hi_pct),
                    "truck_factor_pct": _f(n["truck_factor"]),
                    "truck_tolerance_pct": _f(p.truck_tolerance_pct),
                }
            },
            rule_sets=[MINE_RULE_SET],
            target_type="mine_period_entry",
            target_id=str(e.id),
            project_id=str(e.project_id),
            metadata={"locale": locale},
        )
        return [
            Finding(
                rule_id=r.rule_id,
                severity=str(getattr(r.severity, "value", r.severity)),
                message=r.message,
                suggestion=r.suggestion,
                element_ref=r.element_ref,
            )
            for r in report.results
            if not r.passed
        ]

    async def _entry_out(self, e: MinePeriodEntry, p: MinePeriod, unit: MineUnit, locale: str) -> EntryOut:
        v = await self._volume_of(e)
        n = self._numbers(e, v)
        return EntryOut(
            id=e.id,
            period_id=e.period_id,
            unit_id=e.unit_id,
            unit_code=unit.code,
            unit_name=unit.name,
            unit_type=unit.unit_type,
            underground=unit.unit_type in calc.UNDERGROUND,
            plan_m3=float(e.plan_m3),
            plan_t=_f(e.plan_t),
            plan_advance_m=_f(e.plan_advance_m),
            actual_advance_m=_f(e.actual_advance_m),
            advance_pct=_f(calc.advance_pct(e.actual_advance_m, e.plan_advance_m)),
            density_t_m3=_f(e.density_t_m3),
            actual_m3=_f(n["actual"]),
            actual=None
            if v is None
            else ActualOut(
                volume_id=v.id,
                code=v.code,
                status=v.status,
                method=v.method,
                cell_size_m=_f(v.cell_size_m),
                coverage_pct=float(v.coverage_pct),
                crs_epsg=v.crs_epsg,
                confirmed_by_name=v.confirmed_by_name,
                confirmed_at=v.confirmed_at,
            ),
            compliance_pct=_f(n["compliance"]),
            survey_t=_f(n["survey_t"]),
            truck_loads=e.truck_loads,
            truck_t=_f(e.truck_t),
            truck_factor_pct=_f(n["truck_factor"]),
            truck_source=e.truck_source,
            claim_entry_id=e.claim_entry_id,
            claimed_m3=_f(e.claimed_m3),
            claimed_by_name=e.claimed_by_name,
            claimed_at=e.claimed_at,
            note=e.note,
            findings=await self.findings(e, p, unit, locale),
        )

    @staticmethod
    def _totals(entries: list[EntryOut]) -> Totals:
        with_actual = [e for e in entries if e.actual_m3 is not None]
        actual = sum((calc.dec(e.actual_m3 or 0) for e in with_actual), Decimal(0)) if with_actual else None
        plan_of_actual = sum((calc.dec(e.plan_m3) for e in with_actual), Decimal(0))
        both = [e for e in entries if e.truck_t is not None and e.survey_t is not None]
        truck = sum((calc.dec(e.truck_t or 0) for e in both), Decimal(0)) if both else None
        survey_of_truck = sum((calc.dec(e.survey_t or 0) for e in both), Decimal(0))
        surveyed = [e for e in entries if e.survey_t is not None]
        return Totals(
            plan_m3=float(sum((calc.dec(e.plan_m3) for e in entries), Decimal(0))),
            actual_m3=_f(actual),
            compliance_pct=_f(calc.compliance_pct(actual, plan_of_actual)) if actual is not None else None,
            survey_t=_f(sum((calc.dec(e.survey_t or 0) for e in surveyed), Decimal(0))) if surveyed else None,
            truck_t=_f(truck),
            truck_factor_pct=_f(calc.truck_factor_pct(truck, survey_of_truck)) if truck is not None else None,
            units=len(entries),
        )

    async def detail(self, p: MinePeriod, locale: str = "en") -> PeriodDetail:
        units = {u.id: u for u in await self.repo.list_units(p.project_id)}
        entries = [
            await self._entry_out(e, p, units[e.unit_id], locale)
            for e in await self.repo.entries_of(p.id)
            if e.unit_id in units
        ]
        return PeriodDetail(
            **self._period_out(p, len(entries)).model_dump(),
            entries=entries,
            totals=self._totals(entries),
        )

    # ── Entries: write ─────────────────────────────────────────────────────

    async def get_entry(self, entry_id: uuid.UUID) -> MinePeriodEntry:
        e = await self.repo.get_entry(entry_id)
        if e is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Line not found")
        return e

    async def _unit_for(self, project_id: uuid.UUID, data: EntryCreate, user_id: str) -> MineUnit:
        if data.unit_id is not None:
            u = await self.get_unit(data.unit_id)
            if u.project_id != project_id:
                raise _err(status.HTTP_404_NOT_FOUND, "Unit not found")
            return u
        found = await self.repo.unit_by_name(project_id, data.unit_name)
        if found is not None:
            return found
        await self.create_unit(project_id, UnitCreate(name=data.unit_name, unit_type=data.unit_type), user_id)
        return await self.repo.unit_by_name(project_id, data.unit_name)  # type: ignore[return-value]

    async def add_entry(self, p: MinePeriod, data: EntryCreate, user_id: str, locale: str = "en") -> EntryOut:
        unit = await self._unit_for(p.project_id, data, user_id)
        if await self.repo.entry_for(p.id, unit.id):
            raise _err(status.HTTP_409_CONFLICT, "This unit already has a line in the period")
        density = data.density_t_m3 if data.density_t_m3 is not None else _f(unit.density_t_m3)
        plan_t = data.plan_t
        if plan_t is None and density is not None:
            plan_t = float(calc.survey_tonnes(data.plan_m3, density) or 0)
        e = MinePeriodEntry(
            project_id=p.project_id,
            period_id=p.id,
            unit_id=unit.id,
            plan_m3=_q(data.plan_m3, "0.001"),
            plan_t=_q(plan_t, "0.01"),
            plan_advance_m=_q(data.plan_advance_m, "0.01"),
            density_t_m3=_q(density, "0.0001"),
            created_by=_uuid(user_id),
        )
        await self.repo.add(e)
        return await self._entry_out(e, p, unit, locale)

    async def import_plan(self, p: MinePeriod, data: PlanImport, user_id: str) -> PlanImportResult:
        rows, problems = calc.parse_plan(data.text)
        done = 0
        for r in rows:
            unit = await self.repo.unit_by_name(p.project_id, r.unit)
            if unit is None:
                await self.create_unit(
                    p.project_id,
                    UnitCreate(name=r.unit, unit_type=r.unit_type, density_t_m3=_f(r.density_t_m3)),
                    user_id,
                )
                unit = await self.repo.unit_by_name(p.project_id, r.unit)
            assert unit is not None  # noqa: S101 - just created
            density = r.density_t_m3 if r.density_t_m3 is not None else unit.density_t_m3
            plan_t = r.plan_t if r.plan_t is not None else calc.survey_tonnes(r.plan_m3, density)
            e = await self.repo.entry_for(p.id, unit.id)
            if e is None:
                e = MinePeriodEntry(project_id=p.project_id, period_id=p.id, unit_id=unit.id, created_by=_uuid(user_id))
                await self.repo.add(e)
            elif e.claim_entry_id:
                problems.append(f"{r.unit}: on a progress claim")
                continue
            e.plan_m3 = _q(r.plan_m3, "0.001")  # type: ignore[assignment]
            e.plan_t = _q(plan_t, "0.01")  # type: ignore[assignment]
            e.plan_advance_m = _q(r.plan_advance_m, "0.01")  # type: ignore[assignment]
            e.density_t_m3 = _q(density, "0.0001")  # type: ignore[assignment]
            done += 1
        await self.session.flush()
        return PlanImportResult(imported=done, problems=problems)

    def _open(self, e: MinePeriodEntry) -> None:
        if e.claim_entry_id is not None:
            raise _err(status.HTTP_409_CONFLICT, "The line is on a progress claim and is locked")

    async def update_entry(self, e: MinePeriodEntry, data: EntryUpdate, locale: str = "en") -> EntryOut:
        self._open(e)
        sent = data.model_fields_set
        if "plan_m3" in sent and data.plan_m3 is not None:
            e.plan_m3 = _q(data.plan_m3, "0.001")  # type: ignore[assignment]
        for name, places in (
            ("plan_t", "0.01"),
            ("plan_advance_m", "0.01"),
            ("actual_advance_m", "0.01"),
            ("density_t_m3", "0.0001"),
        ):
            if name in sent:
                setattr(e, name, _q(getattr(data, name), places))
        if data.note is not None:
            e.note = data.note
        await self.session.flush()
        return await self._entry_response(e, locale)

    async def _entry_response(self, e: MinePeriodEntry, locale: str) -> EntryOut:
        return await self._entry_out(e, await self.get_period(e.period_id), await self.get_unit(e.unit_id), locale)

    async def delete_entry(self, e: MinePeriodEntry) -> None:
        self._open(e)
        v = await self._volume_of(e)
        if v is not None and v.status != "draft":
            raise _err(status.HTTP_409_CONFLICT, "The line uses a confirmed volume and cannot be removed")
        await self.repo.delete(e)
        if v is not None:
            await self.volumes.delete_volume(v)

    # ── The actual: a Volumes calculation ──────────────────────────────────

    async def _surface_from_text(
        self, project_id: uuid.UUID, text: str, filename: str, name: str, user_id: str
    ) -> uuid.UUID:
        from app.modules.surfaces_volumes.schemas import SurfaceFromPoints  # noqa: PLC0415
        from app.modules.survey_core.schemas import ImportRequest  # noqa: PLC0415
        from app.modules.survey_core.service import SurveyService  # noqa: PLC0415

        imported = await SurveyService(self.session).import_points(
            project_id,
            ImportRequest(
                text=text, filename=filename, column_preset="PNEZD", default_kind="topo", name=name[:255] or filename
            ),
            user_id,
        )
        surface = await self.volumes.surface_from_points(
            project_id, SurfaceFromPoints(name=name[:255] or filename, point_set_ids=[imported.point_set.id]), user_id
        )
        return surface.id

    async def compute_actual(
        self, e: MinePeriodEntry, data: ComputeActual, user_id: str, locale: str = "en"
    ) -> EntryOut:
        from app.modules.surfaces_volumes.schemas import VolumeCreate  # noqa: PLC0415

        self._open(e)
        old = await self._volume_of(e)
        if old is not None and old.status != "draft":
            raise _err(
                status.HTTP_409_CONFLICT,
                "The actual is confirmed: duplicate the volume on the Volumes page to change it",
            )
        p, unit = await self.get_period(e.period_id), await self.get_unit(e.unit_id)
        start, end = data.start_surface_id, data.end_surface_id
        tag = f"{unit.name} {p.label}"
        if start is None:
            start = await self._surface_from_text(
                p.project_id, data.start_text, data.start_filename, f"{tag} start", user_id
            )
        if end is None:
            end = await self._surface_from_text(p.project_id, data.end_text, data.end_filename, f"{tag} end", user_id)
        v = await self.volumes.create_volume(
            p.project_id,
            VolumeCreate(
                name=f"Mine actual {tag}",
                base_surface_id=start,
                compare_surface_id=end,
                method="grid",
                cell_size_m=data.cell_size_m,
                material=unit.name,
            ),
            user_id,
        )
        e.actual_volume_id = v.id
        await self.session.flush()
        if old is not None:
            await self.volumes.delete_volume(old)
        await self._audit(
            "update", "mine_period_entry", e.id, user_id, {"actual_volume": v.code, "cut_m3": str(v.cut_m3)}
        )
        return await self._entry_response(e, locale)

    async def confirm_actual(
        self, e: MinePeriodEntry, data: ConfirmActual, user_id: str, locale: str = "en"
    ) -> EntryOut:
        from app.modules.surfaces_volumes.schemas import ConfirmRequest  # noqa: PLC0415

        v = await self._volume_of(e)
        if v is None:
            raise _bad("Compute the actual first")
        if v.status == "draft":
            await self.volumes.confirm(v, ConfirmRequest(acknowledge=data.acknowledge), user_id, locale)
        return await self._entry_response(e, locale)

    # ── Trucks ─────────────────────────────────────────────────────────────

    async def import_trucks(self, e: MinePeriodEntry, data: TruckLoadsImport, locale: str = "en") -> EntryOut:
        self._open(e)
        unit = await self.get_unit(e.unit_id)
        r = calc.parse_truck_loads(data.text, unit.name)
        if r.rows == 0:
            raise _bad("No truck loads found for this unit: the file needs loads and payload_t columns")
        e.truck_loads, e.truck_t = r.loads, r.tonnes  # type: ignore[assignment]
        e.truck_source = data.filename[:255]
        e.details = {**(e.details or {}), "truck_rows": r.rows, "truck_problems": r.problems}
        await self.session.flush()
        return await self._entry_response(e, locale)

    # ── Claim ──────────────────────────────────────────────────────────────

    async def add_to_claim(self, e: MinePeriodEntry, data: AddToClaim, user_id: str) -> ClaimResult:
        from app.modules.surfaces_volumes.schemas import RecordProgress  # noqa: PLC0415

        self._open(e)
        v = await self._volume_of(e)
        if v is None or v.status not in ("confirmed", "sent"):
            raise _err(status.HTTP_409_CONFLICT, "Confirm the actual before adding it to a claim")
        p, unit = await self.get_period(e.period_id), await self.get_unit(e.unit_id)
        res = await self.volumes.record_progress(
            v,
            RecordProgress(
                position_id=data.position_id,
                period_label=p.label,
                quantity="cut",
                notes=data.notes.strip() or f"Mine survey {unit.name} {p.label}: {float(v.cut_m3):,.1f} m3 ({v.code})",
            ),
            user_id,
        )
        uid = _uuid(user_id)
        e.claim_entry_id = res.entry_id
        e.claimed_m3 = _q(res.quantity_m3, "0.001")  # type: ignore[assignment]
        e.claimed_at = datetime.now(UTC)
        e.claimed_by_name = await self.repo.user_name(uid)
        await self.session.flush()
        await self._audit(
            "update",
            "mine_period_entry",
            e.id,
            user_id,
            {
                "sent_to": "progress_entry",
                "progress_entry_id": str(res.entry_id),
                "m3": res.quantity_m3,
                "volume": v.code,
            },
        )
        return ClaimResult(
            entry_id=e.id,
            progress_entry_id=res.entry_id,
            position_id=res.position_id,
            quantity_m3=res.quantity_m3,
            period_label=res.period_label,
            percent_complete=res.percent_complete,
        )

    # ── Report ─────────────────────────────────────────────────────────────

    async def report_data(self, p: MinePeriod, locale: str = "en") -> dict[str, Any]:
        d = await self.detail(p, locale)
        crs = {e.actual.crs_epsg for e in d.entries if e.actual and e.actual.crs_epsg}
        return {
            "period": d.model_dump(mode="json", exclude={"entries", "totals"}),
            "entries": [e.model_dump(mode="json") for e in d.entries],
            "totals": d.totals.model_dump(mode="json"),
            "crs_epsg": sorted(crs)[0] if len(crs) == 1 else None,
        }


__all__ = ["MineService"]
