# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scheduling profiles and recalculation under a profile.

A profile is a project's named set of CPM options. Recalculating a schedule
with one runs :func:`app.core.cpm.calculate_cpm` with
:class:`~app.core.cpm_profile.SchedulingOptions` built from the profile, the
schedule's data date and every activity's progress and actual dates (taken
from the progress records, the audit trail of progress). The preview names,
per activity, which setting moved its dates or its critical flag: each
non-default setting is reverted on its own and the run repeated, and an
activity that comes out different without that setting was moved by it.
Apply writes the same dates the preview showed. All writes ``flush`` only.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.cpm import calculate_cpm
from app.core.cpm_profile import ActivityStatus, SchedulingOptions
from app.core.events import publish_after_commit
from app.modules.schedule.models import (
    Activity,
    ProgressUpdate,
    Schedule,
    ScheduleProgressEntry,
)
from app.modules.schedule.profile_models import SchedulingProfile
from app.modules.schedule.profile_schemas import SchedulingProfileCreate, SchedulingProfileUpdate
from app.modules.schedule.service import ScheduleService, _str_to_float, inclusive_end_from_cpm

logger = logging.getLogger(__name__)

#: The settings a profile carries, with the built-in value used when a project
#: has no profile. The built-in values reproduce the plain planning pass.
BUILTIN_SETTINGS: dict[str, Any] = {
    "progress_mode": "retained_logic",
    "lag_calendar": "elapsed",
    "open_ends": "project_finish",
    "critical_rule": "total_float",
    "critical_float_threshold": 0,
}
PROFILE_SETTINGS: tuple[str, ...] = tuple(BUILTIN_SETTINGS)

#: Settings that move dates; the others only move float and the critical flag.
_DATE_SETTINGS: tuple[str, ...] = ("progress_mode", "lag_calendar")
_CRITICAL_SETTINGS: tuple[str, ...] = ("open_ends", "critical_rule", "critical_float_threshold")
#: Progress records whose actual dates count. A draft is not yet a statement.
_COUNTED_UPDATE_STATUSES: tuple[str, ...] = ("submitted", "approved")
_PROFILE_KEY = "scheduling_profile_id"


def _iso_day(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _shift(before: str | None, after: str) -> int:
    old, new = _iso_day(before), _iso_day(after)
    if old is None or new is None:
        return 0
    return (new - old).days


async def load_recorded_actuals(
    session: AsyncSession, activity_ids: list[uuid.UUID]
) -> dict[str, tuple[date | None, date | None]]:
    """Earliest recorded actual start and latest actual finish per activity.

    Read from the two progress records: submitted or approved progress updates
    and field progress entries. Activities with neither are absent.
    """
    found: dict[str, list[date | None]] = {}
    if not activity_ids:
        return {}

    def _take(aid: object, start: object, finish: object) -> None:
        slot = found.setdefault(str(aid), [None, None])
        s, f = _iso_day(start), _iso_day(finish)
        if s is not None and (slot[0] is None or s < slot[0]):
            slot[0] = s
        if f is not None and (slot[1] is None or f > slot[1]):
            slot[1] = f

    rows = await session.execute(
        select(ProgressUpdate.activity_id, ProgressUpdate.actual_start, ProgressUpdate.actual_finish).where(
            ProgressUpdate.activity_id.in_(activity_ids),
            ProgressUpdate.status.in_(_COUNTED_UPDATE_STATUSES),
        )
    )
    for aid, start, finish in rows.all():
        _take(aid, start, finish)
    rows = await session.execute(
        select(
            ScheduleProgressEntry.task_id,
            ScheduleProgressEntry.actual_start_date,
            ScheduleProgressEntry.actual_finish_date,
        ).where(ScheduleProgressEntry.task_id.in_(activity_ids))
    )
    for aid, start, finish in rows.all():
        _take(aid, start, finish)
    return {k: (v[0], v[1]) for k, v in found.items()}


@dataclass
class _Network:
    """Everything one schedule's recalculation needs, loaded once."""

    schedule: Schedule
    activities: list[Activity]
    act_dicts: list[dict[str, object]]
    rel_dicts: list[dict[str, object]]
    calendar: dict
    activity_calendars: dict[str, dict]
    origin: date
    data_date: int | None
    status: dict[str, ActivityStatus]


@dataclass
class EffectiveProfile:
    """The profile a schedule recalculates with and where it came from."""

    profile: SchedulingProfile | None
    settings: dict[str, Any]
    source: str


class SchedulingProfileService:
    """CRUD for profiles, profile choice per schedule, and recalculation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.base = ScheduleService(session)

    # ── Profiles ──────────────────────────────────────────────────────────

    async def list_for_project(self, project_id: uuid.UUID) -> list[SchedulingProfile]:
        stmt = (
            select(SchedulingProfile)
            .where(SchedulingProfile.project_id == project_id)
            .order_by(SchedulingProfile.is_default.desc(), SchedulingProfile.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, profile_id: uuid.UUID) -> SchedulingProfile:
        profile = await self.session.get(SchedulingProfile, profile_id)
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduling profile not found")
        return profile

    async def _clear_default(self, project_id: uuid.UUID, keep: uuid.UUID | None) -> None:
        stmt = update(SchedulingProfile).where(
            SchedulingProfile.project_id == project_id, SchedulingProfile.is_default.is_(True)
        )
        if keep is not None:
            stmt = stmt.where(SchedulingProfile.id != keep)
        await self.session.execute(stmt.values(is_default=False))

    async def _assert_unique_name(self, project_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> None:
        stmt = select(SchedulingProfile.id).where(
            SchedulingProfile.project_id == project_id, SchedulingProfile.name == name
        )
        if exclude is not None:
            stmt = stmt.where(SchedulingProfile.id != exclude)
        if (await self.session.execute(stmt)).first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "scheduling_profile_name_taken", "message": "A profile with this name exists."},
            )

    async def create(self, data: SchedulingProfileCreate, actor_id: str | None) -> SchedulingProfile:
        await self._assert_unique_name(data.project_id, data.name)
        if data.is_default:
            await self._clear_default(data.project_id, None)
        profile = SchedulingProfile(**data.model_dump(), created_by=str(actor_id) if actor_id else None)
        self.session.add(profile)
        await self.session.flush()
        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="schedule_scheduling_profile",
            entity_id=profile.id,
            action="created",
            module="oe_schedule",
            after_state={k: getattr(profile, k) for k in PROFILE_SETTINGS},
        )
        return profile

    async def update(
        self, profile_id: uuid.UUID, data: SchedulingProfileUpdate, actor_id: str | None
    ) -> SchedulingProfile:
        profile = await self.get(profile_id)
        fields = data.model_dump(exclude_unset=True)
        if fields.get("name") and fields["name"] != profile.name:
            await self._assert_unique_name(profile.project_id, fields["name"], exclude=profile.id)
        before = {k: getattr(profile, k) for k in PROFILE_SETTINGS}
        if fields.get("is_default"):
            await self._clear_default(profile.project_id, profile.id)
        for key, value in fields.items():
            if value is not None:
                setattr(profile, key, value)
        await self.session.flush()
        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="schedule_scheduling_profile",
            entity_id=profile.id,
            action="updated",
            module="oe_schedule",
            before_state=before,
            after_state={k: getattr(profile, k) for k in PROFILE_SETTINGS},
        )
        return profile

    async def delete(self, profile_id: uuid.UUID, actor_id: str | None) -> None:
        profile = await self.get(profile_id)
        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="schedule_scheduling_profile",
            entity_id=profile.id,
            action="deleted",
            module="oe_schedule",
            before_state={"name": profile.name, **{k: getattr(profile, k) for k in PROFILE_SETTINGS}},
        )
        await self.session.delete(profile)
        await self.session.flush()

    # ── Choice per schedule ───────────────────────────────────────────────

    async def resolve(self, schedule: Schedule, override_id: uuid.UUID | None = None) -> EffectiveProfile:
        """The profile to use: an explicit one, the schedule's, the project default, the built-in."""
        if override_id is not None:
            profile = await self.get(override_id)
            if profile.project_id != schedule.project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduling profile not found")
            return EffectiveProfile(profile, self.settings_of(profile), "schedule")
        meta = schedule.metadata_ if isinstance(schedule.metadata_, dict) else {}
        raw = meta.get(_PROFILE_KEY)
        if raw:
            try:
                profile = await self.session.get(SchedulingProfile, uuid.UUID(str(raw)))
            except ValueError:
                profile = None
            if profile is not None and profile.project_id == schedule.project_id:
                return EffectiveProfile(profile, self.settings_of(profile), "schedule")
        stmt = select(SchedulingProfile).where(
            SchedulingProfile.project_id == schedule.project_id, SchedulingProfile.is_default.is_(True)
        )
        default = (await self.session.execute(stmt.limit(1))).scalars().first()
        if default is not None:
            return EffectiveProfile(default, self.settings_of(default), "project_default")
        return EffectiveProfile(None, dict(BUILTIN_SETTINGS), "builtin")

    @staticmethod
    def settings_of(profile: SchedulingProfile) -> dict[str, Any]:
        return {key: getattr(profile, key) for key in PROFILE_SETTINGS}

    async def assign(self, schedule_id: uuid.UUID, profile_id: uuid.UUID | None, actor_id: str | None) -> Schedule:
        schedule = await self.base.get_schedule(schedule_id)
        if profile_id is not None:
            profile = await self.get(profile_id)
            if profile.project_id != schedule.project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduling profile not found")
        meta = dict(schedule.metadata_ or {})
        previous = meta.get(_PROFILE_KEY)
        if profile_id is None:
            meta.pop(_PROFILE_KEY, None)
        else:
            meta[_PROFILE_KEY] = str(profile_id)
        await self.base.schedule_repo.update_fields(schedule_id, metadata_=meta)
        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="schedule",
            entity_id=schedule_id,
            action="scheduling_profile_assigned",
            module="oe_schedule",
            before_state={_PROFILE_KEY: previous},
            after_state={_PROFILE_KEY: str(profile_id) if profile_id else None},
        )
        return await self.base.get_schedule(schedule_id)

    # ── Network loading ───────────────────────────────────────────────────

    async def _load(self, schedule_id: uuid.UUID) -> _Network:
        schedule = await self.base.get_schedule(schedule_id)
        activities, _ = await self.base.list_activities_for_schedule(schedule_id, limit=10_000)
        if not activities:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "schedule_has_no_activities", "message": "Schedule has no activities"},
            )
        relationships = await self.base.relationship_repo.list_for_schedule(schedule_id)
        actuals = await load_recorded_actuals(self.session, [a.id for a in activities])
        data_day = _iso_day(schedule.data_date)

        origin = self.base._resolve_project_start(schedule, activities)
        for start, finish in actuals.values():
            for d in (start, finish):
                if d is not None and d < origin:
                    origin = d
        if data_day is not None and data_day < origin:
            origin = data_day

        has_predecessor = {str(r.successor_id) for r in relationships}
        activity_calendars = await self.base._resolve_activity_calendars(activities, schedule.project_id)
        act_dicts: list[dict[str, object]] = []
        status_map: dict[str, ActivityStatus] = {}
        for a in activities:
            aid = str(a.id)
            entry: dict[str, object] = {
                "id": aid,
                "duration": a.duration_days or 0,
                "name": a.name,
                "start_offset": 0 if aid in has_predecessor else self.base._activity_start_offset(a, origin),
            }
            if aid in activity_calendars:
                entry["calendar"] = activity_calendars[aid]
            act_dicts.append(entry)

            pct = _str_to_float(a.progress_pct)
            start, finish = actuals.get(aid, (None, None))
            if pct < 100.0:
                finish = None
            if pct > 0.0 or start is not None or finish is not None:
                status_map[aid] = ActivityStatus(
                    actual_start=(start - origin).days if start is not None else None,
                    actual_finish=(finish - origin).days if finish is not None else None,
                    percent_complete=pct,
                    remaining_duration=a.remaining_duration,
                )
        rel_dicts = [
            {
                "predecessor_id": str(r.predecessor_id),
                "successor_id": str(r.successor_id),
                "type": r.relationship_type,
                "lag": r.lag_days,
            }
            for r in relationships
        ]
        return _Network(
            schedule=schedule,
            activities=activities,
            act_dicts=act_dicts,
            rel_dicts=rel_dicts,
            calendar=await self.base._resolve_schedule_default_calendar(schedule),
            activity_calendars=activity_calendars,
            origin=origin,
            data_date=(data_day - origin).days if data_day is not None else None,
            status=status_map,
        )

    async def _run(self, net: _Network, options: SchedulingOptions) -> dict[str, dict]:
        rows = await calculate_cpm(
            net.act_dicts,
            net.rel_dicts,
            calendar=net.calendar,
            project_start_date=net.origin.isoformat(),
            options=options,
        )
        return {r["id"]: r for r in rows}

    def _dates(self, net: _Network, row: dict) -> tuple[str, str]:
        start = date.fromordinal(net.origin.toordinal() + int(row["early_start"])).isoformat()
        end = inclusive_end_from_cpm(
            row["early_start"],
            row["early_finish"],
            net.activity_calendars.get(row["id"], net.calendar),
            net.origin,
        )
        return start, end

    # ── Recalculation ─────────────────────────────────────────────────────

    async def recalculate(
        self,
        schedule_id: uuid.UUID,
        *,
        profile_id: uuid.UUID | None = None,
        apply: bool = False,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Preview (or apply) a recalculation and attribute every change to a setting."""
        net = await self._load(schedule_id)
        effective = await self.resolve(net.schedule, profile_id)
        settings = effective.settings
        options = SchedulingOptions(**settings, data_date=net.data_date, status=net.status)
        main = await self._run(net, options)

        variants: dict[str, dict[str, dict]] = {}
        for key in PROFILE_SETTINGS:
            if settings[key] != BUILTIN_SETTINGS[key]:
                variants[key] = await self._run(net, replace(options, **{key: BUILTIN_SETTINGS[key]}))
        if net.data_date is not None or net.status:
            variants["status"] = await self._run(net, replace(options, data_date=None, status={}))

        main_dates = {aid: self._dates(net, row) for aid, row in main.items()}
        rows: list[dict[str, Any]] = []
        effects: dict[str, int] = dict.fromkeys(variants, 0)
        updates: list[dict[str, object]] = []
        for act in net.activities:
            aid = str(act.id)
            row = main[aid]
            new_start, new_end = main_dates[aid]
            changed_by: list[str] = []
            for key, variant in variants.items():
                other = variant[aid]
                if key in _DATE_SETTINGS or key == "status":
                    moved = self._dates(net, other) != (new_start, new_end)
                else:
                    moved = other["is_critical"] != row["is_critical"] or other["total_float"] != row["total_float"]
                if moved:
                    changed_by.append(key)
                    effects[key] += 1
            date_changed = (new_start, new_end) != (act.start_date, act.end_date)
            rows.append(
                {
                    "activity_id": act.id,
                    "activity_code": act.activity_code,
                    "name": act.name,
                    "current_start": act.start_date,
                    "current_end": act.end_date,
                    "new_start": new_start,
                    "new_end": new_end,
                    "start_shift_days": _shift(act.start_date, new_start),
                    "finish_shift_days": _shift(act.end_date, new_end),
                    "total_float": row["total_float"],
                    "was_critical": bool(act.is_critical),
                    "is_critical": bool(row["is_critical"]),
                    "completed": bool(row["completed"]),
                    "started": bool(row["started"]),
                    "out_of_sequence": bool(row["out_of_sequence"]),
                    "on_longest_path": bool(row["on_longest_path"]),
                    "open_start": bool(row["open_start"]),
                    "open_finish": bool(row["open_finish"]),
                    "changed_by": changed_by,
                    "_changed": date_changed or bool(act.is_critical) != bool(row["is_critical"]),
                }
            )
            updates.append(
                {
                    "id": act.id,
                    "start_date": new_start,
                    "end_date": new_end,
                    "early_start": str(row["early_start"]),
                    "early_finish": str(row["early_finish"]),
                    "late_start": str(row["late_start"]),
                    "late_finish": str(row["late_finish"]),
                    "total_float": row["total_float"],
                    "free_float": row["free_float"],
                    "is_critical": bool(row["is_critical"]),
                    "color": "#ef4444" if row["is_critical"] else "#0071e3",
                }
            )

        current_finish = max((a.end_date for a in net.activities if a.end_date), default=None)
        new_finish = max((d[1] for d in main_dates.values()), default=None)
        changed_count = sum(1 for r in rows if r.pop("_changed"))
        result: dict[str, Any] = {
            "schedule_id": net.schedule.id,
            "applied": False,
            "profile_id": effective.profile.id if effective.profile else None,
            "profile_name": effective.profile.name if effective.profile else None,
            "source": effective.source,
            "settings": settings,
            "data_date": net.schedule.data_date,
            "current_finish": current_finish,
            "new_finish": new_finish,
            "changed_count": changed_count,
            "critical_count": sum(1 for r in rows if r["is_critical"]),
            "out_of_sequence_count": sum(1 for r in rows if r["out_of_sequence"]),
            "open_end_count": sum(1 for r in rows if r["open_finish"] and not r["completed"]),
            "setting_effects": effects,
            "activities": rows,
        }
        if apply:
            await self._apply(net, result, updates, actor_id)
            result["applied"] = True
        return result

    async def _apply(
        self, net: _Network, result: dict[str, Any], updates: list[dict[str, object]], actor_id: str | None
    ) -> None:
        schedule_id = net.schedule.id
        project_id = net.schedule.project_id
        await self.base.activity_repo.bulk_update_fields(updates)
        await self.base.sync_schedule_end_date(schedule_id)
        schedule = await self.base.get_schedule(schedule_id)
        meta = dict(schedule.metadata_ or {})
        meta["last_recalculation"] = {
            "profile_id": str(result["profile_id"]) if result["profile_id"] else None,
            "profile_name": result["profile_name"],
            "source": result["source"],
            "settings": result["settings"],
            "data_date": result["data_date"],
            "changed_count": result["changed_count"],
            "at": datetime.now(UTC).isoformat(),
            "by": str(actor_id) if actor_id else None,
        }
        await self.base.schedule_repo.update_fields(schedule_id, metadata_=meta)
        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="schedule",
            entity_id=schedule_id,
            action="recalculated_with_profile",
            module="oe_schedule",
            metadata={
                "profile_id": meta["last_recalculation"]["profile_id"],
                "settings": result["settings"],
                "changed_count": result["changed_count"],
                "setting_effects": result["setting_effects"],
                "finish_before": result["current_finish"],
                "finish_after": result["new_finish"],
            },
        )
        publish_after_commit(
            self.session,
            "schedule.rescheduled",
            {
                "schedule_id": str(schedule_id),
                "project_id": str(project_id),
                "count": len(updates),
                "profile_id": meta["last_recalculation"]["profile_id"],
            },
            source_module="oe_schedule",
        )
        logger.info("Schedule %s recalculated with profile settings %s", schedule_id, result["settings"])
