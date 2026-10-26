# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Geofenced time clock service​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

A worker taps clock-in and clock-out on a phone. Each tap stores the position
at that moment only, never a track, and only for a worker whose consent is on
record. The position is compared with the project's site geofences: inside is
an ordinary clock, outside is flagged (never refused) and waits for a
supervisor's approval with a reason. Paired clocks are shifts, and the shifts
of a day build the draft field timesheet, which then follows the timesheet's
usual road: validation, submission, approval, payroll, cost actuals.

Day boundaries are UTC calendar days of the clock-in instant.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.modules.field_time import events as ft_events
from app.modules.field_time import field_time_math as ft
from app.modules.field_time import geofence_math as gm
from app.modules.field_time.clock_repository import ClockRepository
from app.modules.field_time.clock_schemas import (
    ClockConsentIn,
    ClockEventCreate,
    ClockSettingsIn,
    GeofenceCreate,
    GeofenceUpdate,
)
from app.modules.field_time.models import (
    FieldClockConsent,
    FieldClockEvent,
    FieldClockSettings,
    FieldSiteGeofence,
    FieldTimesheet,
    FieldTimesheetLine,
)
from app.modules.field_time.schemas import FieldTimesheetCreate, FieldTimesheetLineCreate

logger = logging.getLogger(__name__)

_RULE_SET = "field_time"
CLOCK_SOURCE = "clock"
CONSENT_TEXT_VERSION = "1"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def fence_spec(row: FieldSiteGeofence) -> gm.FenceSpec:
    """Translate an ORM fence into the pure geometry spec."""
    return gm.FenceSpec(
        fence_id=str(row.id),
        name=row.name or "",
        shape=row.shape,
        center_lat=_f(row.center_lat),
        center_lng=_f(row.center_lng),
        radius_m=_f(row.radius_m),
        polygon=tuple((float(p[0]), float(p[1])) for p in (row.polygon or [])),
        tolerance_m=float(row.tolerance_m or 0),
    )


def event_dict(ev: FieldClockEvent) -> dict[str, Any]:
    """The plain shape the pure engine and the validation rules read."""
    return {
        "id": str(ev.id),
        "worker": str(ev.resource_id),
        "kind": ev.kind,
        "occurred_at": _as_utc(ev.occurred_at),
        "geofence_id": str(ev.geofence_id) if ev.geofence_id else None,
        "approval_status": ev.approval_status,
        "inside": bool(ev.inside),
        "distance_m": _f(ev.distance_m),
    }


def _not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"This {what} does not exist or has been removed. Refresh the page and try again.",
    )


class ClockService:
    """Business logic for geofences, consent and clock events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ClockRepository(session)

    # ── Geofences ────────────────────────────────────────────────────────────

    async def list_geofences(self, project_id: uuid.UUID) -> list[FieldSiteGeofence]:
        """All fences of a project."""
        return await self.repo.list_geofences(project_id)

    async def get_geofence(self, geofence_id: uuid.UUID) -> FieldSiteGeofence:
        """One fence (404 when missing)."""
        row = await self.repo.get_geofence(geofence_id)
        if row is None:
            raise _not_found("site geofence")
        return row

    @staticmethod
    def _assert_fence_usable(row: FieldSiteGeofence) -> None:
        problems = gm.validate_fence(fence_spec(row))
        if problems:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "geofence_invalid",
                    "problems": problems,
                    "message": (
                        "This site boundary cannot be used: a circle needs a centre and a radius, "
                        "a polygon needs at least three points on the map."
                    ),
                },
            )

    async def create_geofence(self, data: GeofenceCreate, user_id: str | None) -> FieldSiteGeofence:
        """Create a fence after checking its geometry."""
        row = FieldSiteGeofence(
            project_id=data.project_id,
            name=data.name.strip() or "Site",
            shape=data.shape,
            center_lat=None if data.center_lat is None else Decimal(str(data.center_lat)),
            center_lng=None if data.center_lng is None else Decimal(str(data.center_lng)),
            radius_m=None if data.radius_m is None else Decimal(str(data.radius_m)),
            polygon=[[float(a), float(b)] for a, b in data.polygon],
            tolerance_m=Decimal(str(data.tolerance_m)),
            supervisor_user_ids=[str(u) for u in data.supervisor_user_ids],
            default_cost_code=data.default_cost_code.strip(),
            active=data.active,
            created_by=uuid.UUID(str(user_id)) if user_id else None,
        )
        self._assert_fence_usable(row)
        await self.repo.add(row)
        return row

    async def update_geofence(self, geofence_id: uuid.UUID, data: GeofenceUpdate) -> FieldSiteGeofence:
        """Patch a fence and re-check its geometry."""
        row = await self.get_geofence(geofence_id)
        fields = data.model_dump(exclude_unset=True)
        for key in ("center_lat", "center_lng", "radius_m", "tolerance_m"):
            if key in fields:
                value = fields.pop(key)
                setattr(row, key, None if value is None else Decimal(str(value)))
        if "polygon" in fields:
            row.polygon = [[float(a), float(b)] for a, b in (fields.pop("polygon") or [])]
        if "supervisor_user_ids" in fields:
            row.supervisor_user_ids = [str(u) for u in (fields.pop("supervisor_user_ids") or [])]
        for key, value in fields.items():
            if value is not None:
                setattr(row, key, value.strip() if isinstance(value, str) else value)
        self._assert_fence_usable(row)
        await self.session.flush()
        return row

    async def delete_geofence(self, geofence_id: uuid.UUID) -> None:
        """Delete a fence; past clocks keep their inside/outside verdict."""
        await self.repo.delete(await self.get_geofence(geofence_id))

    # ── Settings ─────────────────────────────────────────────────────────────

    async def get_settings(self, project_id: uuid.UUID) -> FieldClockSettings:
        """The project's settings, defaults when none were saved (not persisted)."""
        row = await self.repo.get_settings(project_id)
        if row is None:
            row = FieldClockSettings(
                project_id=project_id,
                enabled=True,
                retention_days=gm.DEFAULT_RETENTION_DAYS,
                default_break_minutes=0,
                consent_text_version=CONSENT_TEXT_VERSION,
            )
        return row

    async def put_settings(self, data: ClockSettingsIn) -> FieldClockSettings:
        """Create or replace the project's settings."""
        row = await self.repo.get_settings(data.project_id)
        if row is None:
            row = FieldClockSettings(project_id=data.project_id, consent_text_version=CONSENT_TEXT_VERSION)
            await self.repo.add(row)
        row.enabled = data.enabled
        row.retention_days = data.retention_days
        row.default_break_minutes = data.default_break_minutes
        await self.session.flush()
        return row

    # ── Consent ──────────────────────────────────────────────────────────────

    async def get_consent(self, project_id: uuid.UUID, resource_id: uuid.UUID) -> FieldClockConsent | None:
        """A worker's consent row, None when never asked."""
        return await self.repo.get_consent(project_id, resource_id)

    async def set_consent(self, data: ClockConsentIn, user_id: str | None) -> FieldClockConsent:
        """Record consent or its withdrawal. Withdrawal erases stored positions."""
        row = await self.repo.get_consent(data.project_id, data.resource_id)
        now = _utcnow()
        if row is None:
            row = FieldClockConsent(project_id=data.project_id, resource_id=data.resource_id)
            await self.repo.add(row)
        row.granted = data.granted
        row.text_version = data.text_version
        row.recorded_by = uuid.UUID(str(user_id)) if user_id else None
        if data.granted:
            row.granted_at = now
            row.withdrawn_at = None
        else:
            row.withdrawn_at = now
            await self._erase_worker_positions(data.project_id, data.resource_id, now)
        await self.session.flush()
        return row

    async def _erase_worker_positions(self, project_id: uuid.UUID, resource_id: uuid.UUID, now: datetime) -> None:
        events, _ = await self.repo.list_events(project_id, resource_id=resource_id, limit=100_000)
        for ev in events:
            if ev.position_purged_at is None:
                ev.latitude = ev.longitude = ev.accuracy_m = None
                ev.position_purged_at = now

    # ── Clock events ─────────────────────────────────────────────────────────

    async def record_event(self, data: ClockEventCreate, user_id: str | None) -> FieldClockEvent:
        """Store a clock-in or clock-out, flag it when outside every fence."""
        if data.client_op_id:
            seen = await self.repo.get_by_client_op(data.project_id, data.client_op_id)
            if seen is not None:
                return seen
        settings = await self.get_settings(data.project_id)
        if not settings.enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "clock_disabled", "message": "The time clock is switched off for this project."},
            )
        consent = await self.repo.get_consent(data.project_id, data.resource_id)
        if consent is None or not consent.granted:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "consent_required",
                    "message": (
                        "This worker has not agreed to the position check at clock-in and clock-out. "
                        "Ask for consent first, or book the hours on a timesheet."
                    ),
                },
            )
        now = _utcnow()
        occurred = _as_utc(data.occurred_at) if data.occurred_at else now
        last = await self.repo.last_event_for(data.project_id, data.resource_id, before=occurred)
        open_in = last if last is not None and last.kind == gm.KIND_IN else None
        if data.kind == gm.KIND_IN and open_in is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "already_clocked_in",
                    "event_id": str(open_in.id),
                    "message": "This worker is already clocked in. Clock out first.",
                },
            )
        if data.kind == gm.KIND_OUT and open_in is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "not_clocked_in",
                    "message": "This worker is not clocked in, so there is nothing to close.",
                },
            )

        fences = [fence_spec(f) for f in await self.repo.list_geofences(data.project_id, active_only=True)]
        hit = gm.evaluate_fences(data.latitude, data.longitude, fences)
        approval = gm.approval_for(hit)
        event = FieldClockEvent(
            project_id=data.project_id,
            resource_id=data.resource_id,
            kind=data.kind,
            occurred_at=occurred,
            latitude=Decimal(str(round(data.latitude, 7))),
            longitude=Decimal(str(round(data.longitude, 7))),
            accuracy_m=None if data.accuracy_m is None else Decimal(str(round(data.accuracy_m, 2))),
            geofence_id=uuid.UUID(hit.fence_id) if hit else None,
            inside=True if hit is None else hit.inside,
            distance_m=None if hit is None else Decimal(str(hit.distance_m)),
            approval_status=approval,
            pair_event_id=open_in.id if (data.kind == gm.KIND_OUT and open_in) else None,
            client_op_id=data.client_op_id,
            recorded_by=uuid.UUID(str(user_id)) if user_id else None,
            note=data.note,
        )
        # A clock replayed after its own retention window never stores a position.
        if occurred < _day_window(gm.purge_cutoff(now.date(), settings.retention_days))[0]:
            event.latitude = event.longitude = event.accuracy_m = None
            event.position_purged_at = now
        await self.repo.add(event)
        # Retention runs on every write, so no position outlives its window
        # because nobody pressed a button.
        await self.purge(data.project_id, settings=settings)

        payload = self._payload(event, hit)
        ft_events.publish_clock_event(ft_events.CLOCK_IN if data.kind == gm.KIND_IN else ft_events.CLOCK_OUT, payload)
        if approval == gm.APPROVAL_PENDING:
            ft_events.publish_clock_event(ft_events.CLOCK_FLAGGED, payload)
            await self._notify_supervisors(event, hit)
        return event

    async def record_crew_event(self, data: ClockEventCreate, user_id: str | None) -> dict[str, Any]:
        """Clock a whole crew from the foreman's phone, one event per member.

        Members are the crew's ``crew_member`` links in the resources module.
        A member without consent, or already in the requested state, is
        skipped and named in the answer rather than failing the crew.
        """
        from app.modules.resources.models import ResourceLink

        stmt = select(ResourceLink.secondary_resource_id).where(
            ResourceLink.primary_resource_id == data.resource_id,
            ResourceLink.link_type == "crew_member",
        )
        member_ids = [data.resource_id, *(await self.session.execute(stmt)).scalars().all()]
        recorded: list[FieldClockEvent] = []
        skipped: list[dict[str, str]] = []
        for index, member in enumerate(dict.fromkeys(member_ids)):
            op_id = f"{data.client_op_id}:{index}" if data.client_op_id else None
            try:
                recorded.append(
                    await self.record_event(
                        data.model_copy(update={"resource_id": member, "client_op_id": op_id}), user_id
                    )
                )
            except HTTPException as exc:
                code = exc.detail.get("code", "error") if isinstance(exc.detail, dict) else "error"
                skipped.append({"resource_id": str(member), "code": str(code)})
        return {"events": recorded, "skipped": skipped}

    @staticmethod
    def _payload(event: FieldClockEvent, hit: gm.FenceHit | None) -> dict[str, Any]:
        return {
            "event_id": str(event.id),
            "project_id": str(event.project_id),
            "resource_id": str(event.resource_id),
            "kind": event.kind,
            "occurred_at": _as_utc(event.occurred_at).isoformat(),
            "work_date": _as_utc(event.occurred_at).date().isoformat(),
            "inside": bool(event.inside),
            "geofence_id": str(event.geofence_id) if event.geofence_id else None,
            "geofence_name": hit.name if hit else None,
            "distance_m": hit.distance_m if hit else None,
            "approval_status": event.approval_status,
        }

    async def _supervisors(self, project_id: uuid.UUID, fence_id: uuid.UUID | None) -> list[str]:
        ids: list[str] = []
        if fence_id is not None:
            fence = await self.repo.get_geofence(fence_id)
            ids.extend(str(u) for u in (fence.supervisor_user_ids if fence else []) or [])
        try:
            from app.modules.projects.models import Project

            owner = (await self.session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar()
            if owner:
                ids.append(str(owner))
        except Exception:
            logger.debug("Project owner lookup failed for project=%s", project_id)
        return list(dict.fromkeys(ids))

    async def _notify_supervisors(self, event: FieldClockEvent, hit: gm.FenceHit | None) -> None:
        """Tell each supervisor a clock outside the fence waits for them (best-effort)."""
        try:
            from app.modules.notifications.service import NotificationService

            recipients = await self._supervisors(event.project_id, event.geofence_id)
            if not recipients:
                return
            names = await self.repo.resource_names({event.resource_id})
            await NotificationService(self.session).notify_users(
                recipients,
                notification_type="field_clock_outside",
                title_key="notifications.field_clock.outside.title",
                entity_type="field_clock_event",
                entity_id=str(event.id),
                body_key="notifications.field_clock.outside.body",
                body_context={
                    "worker": names.get(event.resource_id, ""),
                    "site": hit.name if hit else "",
                    "distance": f"{hit.distance_m:.0f}" if hit else "",
                    "kind": event.kind,
                },
                action_url=f"/projects/{event.project_id}/field-time?tab=approvals",
            )
        except Exception:
            logger.debug("Supervisor notification skipped for clock event=%s", event.id, exc_info=True)

    async def get_event(self, event_id: uuid.UUID) -> FieldClockEvent:
        """One clock event (404 when missing)."""
        row = await self.repo.get_event(event_id)
        if row is None:
            raise _not_found("clock event")
        return row

    async def list_events(
        self,
        project_id: uuid.UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        resource_id: uuid.UUID | None = None,
        approval_status: str | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[FieldClockEvent], int]:
        """Events in an inclusive date window."""
        since = _day_window(date_from)[0] if date_from else None
        until = _day_window(date_to)[1] if date_to else None
        return await self.repo.list_events(
            project_id,
            since=since,
            until=until,
            resource_id=resource_id,
            approval_status=approval_status,
            offset=offset,
            limit=limit,
        )

    async def decide(self, event_id: uuid.UUID, *, approve: bool, reason: str, user_id: str | None) -> FieldClockEvent:
        """A supervisor approves or rejects a flagged clock, always with a reason."""
        event = await self.get_event(event_id)
        if event.approval_status not in (gm.APPROVAL_PENDING, gm.APPROVAL_REJECTED) or (
            not approve and event.approval_status == gm.APPROVAL_REJECTED
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "not_pending",
                    "message": f"This clock is '{event.approval_status}' and has nothing waiting for a decision.",
                },
            )
        prior = event.approval_status
        event.approval_status = gm.APPROVAL_APPROVED if approve else gm.APPROVAL_REJECTED
        event.approval_reason = reason.strip()
        event.approved_by = uuid.UUID(str(user_id)) if user_id else None
        event.approved_at = _utcnow()
        await self.session.flush()
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=user_id,
                entity_type="field_clock_event",
                entity_id=str(event.id),
                action="status_changed",
                from_status=prior,
                to_status=event.approval_status,
                reason=event.approval_reason,
                module="field_time",
                parent_entity_type="project",
                parent_entity_id=str(event.project_id),
                before_state={"approval_status": prior},
                after_state={"approval_status": event.approval_status},
            )
        except Exception:
            logger.debug("Audit-log write skipped for clock event=%s", event.id)
        ft_events.publish_clock_event(
            ft_events.CLOCK_DECIDED,
            {**self._payload(event, None), "decision": event.approval_status, "actor_id": user_id},
        )
        return event

    async def status(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Who is on site now, pending approvals, missing clock-outs, today's hours."""
        now = _utcnow()
        events, _ = await self.repo.list_events(project_id, since=now - timedelta(days=7), limit=20_000)
        shifts = gm.pair_shifts([event_dict(e) for e in events])
        by_id = {str(e.id): e for e in events}
        missing = gm.missing_clock_outs(shifts, now)
        missing_ids = {s.in_event_id for s in missing}
        on_site = []
        latest_open: dict[str, gm.Shift] = {}
        for s in shifts:
            if s.ended_at is None and s.in_event_id not in missing_ids:
                latest_open[s.worker] = s
        names = await self.repo.resource_names({uuid.UUID(w) for w in latest_open})
        for worker, s in latest_open.items():
            ev = by_id[s.in_event_id]
            on_site.append(
                {
                    "resource_id": ev.resource_id,
                    "resource_name": names.get(ev.resource_id, ""),
                    "clocked_in_at": _as_utc(ev.occurred_at),
                    "inside": bool(ev.inside),
                    "event_id": ev.id,
                }
            )
        today_start, _ = _day_window(now.date())
        hours = Decimal("0")
        for s in shifts:
            if s.started_at >= today_start:
                end = s.ended_at or now
                hours += Decimal(str(max(0.0, (end - s.started_at).total_seconds()) / 3600))
        on_site.sort(key=lambda r: r["clocked_in_at"])
        return {
            "project_id": project_id,
            "on_site": on_site,
            "on_site_count": len(on_site),
            "pending_approvals": await self.repo.count_pending(project_id),
            "missing_clock_outs": len(missing),
            "today_hours": str(hours.quantize(Decimal("0.01"))),
        }

    # ── Timesheet building ───────────────────────────────────────────────────

    async def build_timesheet(self, project_id: uuid.UUID, day: date, user_id: str | None) -> FieldTimesheet:
        """Build or refresh the draft timesheet of a day from its closed shifts.

        Lines come from shifts that started on the day. Outside clocks are
        included with a note: the ``field_time.clock_outside_unapproved`` rule
        then stops the timesheet being submitted until a supervisor decides.
        A day whose clock timesheet is already submitted or approved is not
        rebuilt; correct it with a reversal like any other.
        """
        from app.modules.field_time.service import FieldTimeService

        start, end = _day_window(day)
        settings = await self.get_settings(project_id)
        events, _ = await self.repo.list_events(
            project_id, since=start - timedelta(days=1), until=end + timedelta(days=1), limit=20_000
        )
        shifts = [
            s
            for s in gm.pair_shifts([event_dict(e) for e in events])
            if start <= s.started_at < end and s.ended_at is not None
        ]
        fences = {str(f.id): f for f in await self.repo.list_geofences(project_id)}
        by_id = {str(e.id): e for e in events}

        existing = await self._clock_timesheet(project_id, day)
        if existing is not None and existing.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "timesheet_locked",
                    "timesheet_id": str(existing.id),
                    "message": f"The clock timesheet for {day} is '{existing.status}'. Reverse it to change its hours.",
                },
            )
        lines: list[FieldTimesheetLineCreate] = []
        for s in sorted(shifts, key=lambda x: (x.worker, x.started_at)):
            fence = fences.get(s.fence_id or "")
            flagged = not gm.shift_is_approved(s)
            lines.append(
                FieldTimesheetLineCreate(
                    resource_id=uuid.UUID(s.worker),
                    hours=Decimal("0"),
                    cost_code=(fence.default_cost_code if fence else "") or "",
                    started_at=s.started_at,
                    ended_at=s.ended_at,
                    break_minutes=gm.effective_break(s, settings.default_break_minutes) or None,
                    note=("Clocked outside the site fence, waiting for approval" if flagged else None),
                )
            )
        service = FieldTimeService(self.session)
        if existing is None:
            timesheet = await service.create_timesheet(
                FieldTimesheetCreate(
                    project_id=project_id,
                    date=day,
                    note="Built from the time clock",
                    metadata={"source": CLOCK_SOURCE},
                    lines=lines,
                ),
                user_id,
            )
        else:
            timesheet = existing
            for line in list(timesheet.lines):
                await self.session.delete(line)
            await self.session.flush()
            for data in lines:
                self.session.add(FieldTimeService._line_from_create(timesheet.id, data))
            await self.session.flush()
            await self.session.refresh(timesheet)
        for s in shifts:
            for eid in (s.in_event_id, s.out_event_id):
                if eid and eid in by_id:
                    by_id[eid].timesheet_id = timesheet.id
        await self.session.flush()
        ft_events.publish_clock_event(
            ft_events.CLOCK_TIMESHEET_BUILT,
            {
                "project_id": str(project_id),
                "timesheet_id": str(timesheet.id),
                "work_date": day.isoformat(),
                "lines": len(lines),
                "flagged_lines": sum(1 for s in shifts if not gm.shift_is_approved(s)),
                "actor_id": user_id,
            },
        )
        return timesheet

    async def _clock_timesheet(self, project_id: uuid.UUID, day: date) -> FieldTimesheet | None:
        stmt = select(FieldTimesheet).where(
            FieldTimesheet.project_id == project_id,
            FieldTimesheet.date == day,
            FieldTimesheet.reverses_id.is_(None),
            FieldTimesheet.status.in_(("draft", "submitted", "approved")),
        )
        for ts in (await self.session.execute(stmt)).scalars().all():
            if (ts.metadata_ or {}).get("source") == CLOCK_SOURCE:
                return ts
        return None

    # ── Validation ───────────────────────────────────────────────────────────

    async def clock_payload(self, project_id: uuid.UUID, day: date) -> dict[str, Any]:
        """The clock block the ``field_time`` rules read for one project-day."""
        start, end = _day_window(day)
        events, _ = await self.repo.list_events(
            project_id, since=start, until=end + timedelta(hours=gm.MISSING_CLOCK_OUT_HOURS), limit=20_000
        )
        names = await self.repo.resource_names({e.resource_id for e in events})
        rows = []
        for e in events:
            d = event_dict(e)
            d["occurred_at"] = d["occurred_at"].isoformat()
            d["worker_name"] = names.get(e.resource_id, "")
            rows.append(d)
        return {"clock_events": rows, "now": _utcnow().isoformat(), "clock_day": day.isoformat()}

    async def validate_day(self, project_id: uuid.UUID, day: date) -> dict[str, Any]:
        """Run the field-time rule set over a day's clock events (read-only)."""
        from app.modules.field_time.service import FieldTimeService

        payload = {"id": f"{project_id}:{day}", "project_id": str(project_id), "date": str(day), "lines": []}
        payload.update(await self.clock_payload(project_id, day))
        report = await validation_engine.validate(
            data=payload,
            rule_sets=[_RULE_SET],
            target_type="field_clock_day",
            target_id=f"{project_id}:{day}",
            project_id=str(project_id),
            metadata={"locale": get_locale(), "operation": "read"},
        )
        return FieldTimeService._report_to_dict(report)

    # ── Retention ────────────────────────────────────────────────────────────

    async def purge(self, project_id: uuid.UUID, *, settings: FieldClockSettings | None = None) -> int:
        """Erase positions older than the retention window; returns rows erased."""
        settings = settings or await self.get_settings(project_id)
        now = _utcnow()
        cutoff = gm.purge_cutoff(now.date(), settings.retention_days)
        return await self.repo.purge_positions(project_id, _day_window(cutoff)[0], now)

    # ── Labour cost (cost control / CVR) ─────────────────────────────────────

    async def labour_cost(
        self, project_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None
    ) -> dict[str, Any]:
        """Approved field labour hours x resource rate in a period.

        Reads approved, non-reversed timesheets (the same set payroll reads) and reports how much of it came from the
        time clock.
        """
        from app.modules.field_time.service import FieldTimeService

        # Same set payroll reads: an approved original that was later reversed
        # has flipped to "reversed", so approved + not-a-reversal is the live set.
        stmt = select(FieldTimesheet).where(
            FieldTimesheet.project_id == project_id,
            FieldTimesheet.status == "approved",
            FieldTimesheet.reverses_id.is_(None),
        )
        if date_from:
            stmt = stmt.where(FieldTimesheet.date >= date_from)
        if date_to:
            stmt = stmt.where(FieldTimesheet.date <= date_to)
        live = list((await self.session.execute(stmt)).scalars().all())
        lines: list[FieldTimesheetLine] = [ln for t in live for ln in t.lines if ln.resource_id is not None]
        service = FieldTimeService(self.session)
        rates = await service._labour_rates([{"resource_id": str(ln.resource_id)} for ln in lines])
        hours = Decimal("0")
        cost = Decimal("0")
        clock_hours = Decimal("0")
        clock_ids = {t.id for t in live if (t.metadata_ or {}).get("source") == CLOCK_SOURCE}
        for ln in lines:
            h = ft.to_decimal(ln.hours)
            hours += h
            cost += h * rates.get(str(ln.resource_id), Decimal("0"))
            if ln.timesheet_id in clock_ids:
                clock_hours += h
        return {
            "project_id": project_id,
            "date_from": date_from,
            "date_to": date_to,
            "labour_hours": str(hours.quantize(Decimal("0.01"))),
            "labour_cost": str(cost.quantize(Decimal("0.01"))),
            "currency": await service._project_base_currency(project_id),
            "timesheets": len(live),
            "from_clock_hours": str(clock_hours.quantize(Decimal("0.01"))),
        }


__all__ = ["CLOCK_SOURCE", "ClockService", "event_dict", "fence_spec"]
