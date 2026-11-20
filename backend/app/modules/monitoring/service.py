# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Business logic for monitoring.

Readings are imported, never typed in by an instrument link. Displacement, rate
and level are always computed from the stored readings and the project's active
threshold profile, so editing a point's axis or switching profile re-judges the
whole history. A reading that crosses to a higher level than the previous one
opens an alert: it snapshots the thresholds, notifies the project owner and the
importer, and from Action up opens a risk draft. Every change writes an audit row.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.monitoring import profiles as profile_lib
from app.modules.monitoring.models import (
    MonitoringAlert,
    MonitoringEpoch,
    MonitoringPoint,
    MonitoringProfile,
    MonitoringReading,
    MonitoringSettings,
)
from app.modules.monitoring.monitoring_math import (
    DEFAULT_AXIS,
    RANK,
    Evaluation,
    Reading,
    Thresholds,
    evaluate,
    forecast,
    ordered,
)
from app.modules.monitoring.readings_io import ParsedReading, ParseResult, parse_readings
from app.modules.monitoring.repository import MonitoringRepository
from app.modules.monitoring.schemas import (
    Acknowledge,
    AlertOut,
    Finding,
    ForecastLevelOut,
    ImportProblem,
    MonitoringSummary,
    PointCreate,
    PointDetail,
    PointOut,
    PointUpdate,
    ProfileCreate,
    ProfileOut,
    ReadingsImport,
    ReadingsPreview,
    ReadingsResult,
    SeriesEntry,
    SettingsOut,
    SettingsUpdate,
    ThresholdsOut,
    ValidationReportOut,
)
from app.modules.monitoring.validators import MONITORING_RULE_SET

logger = logging.getLogger(__name__)

DEMO_DIR = Path(__file__).resolve().parent / "demo" / "riverside"
DEMO_POINTS = (("MP-01", "Pit wall pin 1"), ("MP-02", "Pit wall pin 2"))
_NEED = {"z": "Z", "value": "a value", "horizontal": "E and N", "3d": "E, N and Z"}


def _err(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def not_found() -> HTTPException:
    return _err(status.HTTP_404_NOT_FOUND, "Not found")


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _thresholds_out(t: Thresholds) -> ThresholdsOut:
    return ThresholdsOut(
        alert_mm=_f(t.alert_mm),
        action_mm=_f(t.action_mm),
        alarm_mm=_f(t.alarm_mm),
        rate_alert=_f(t.rate_alert),
        rate_action=_f(t.rate_action),
        rate_alarm=_f(t.rate_alarm),
    )


def _thresholds_from_json(data: dict[str, Any] | None) -> ThresholdsOut:
    data = data or {}
    return ThresholdsOut(**{k: (None if data.get(k) is None else float(data[k])) for k in ThresholdsOut.model_fields})


def _profile_out(p: profile_lib.MonitoringProfile) -> ProfileOut:
    return ProfileOut(
        key=p.key,
        name=p.name,
        source=p.source,  # type: ignore[arg-type]
        country=p.country,
        reference=p.reference,
        edition=p.edition,
        clause=p.clause,
        status=p.status,
        thresholds=_thresholds_out(p.thresholds),
    )


def _alert_out(a: MonitoringAlert) -> AlertOut:
    return AlertOut(
        id=a.id,
        reading_id=a.reading_id,
        level=a.level,  # type: ignore[arg-type]
        displacement_mm=float(a.displacement_mm),
        rate_mm_day=_f(a.rate_mm_day),
        observed_at=a.observed_at,
        profile_label=a.profile_label,
        thresholds=_thresholds_from_json(a.thresholds),
        notified=bool(a.notified),
        risk_id=a.risk_id,
        acknowledged_at=a.acknowledged_at,
        acknowledged_by_name=a.acknowledged_by_name,
        note=a.note,
    )


def _problems(parsed: ParseResult, extra: list[ImportProblem]) -> list[ImportProblem]:
    return [ImportProblem(line=p.line, point_id=p.point_id, message=p.message) for p in parsed.problems] + extra


def infer_axis(r: ParsedReading) -> tuple[str, str]:
    """``(axis, point_type)`` a new point gets from its first reading."""
    if r.e is not None and r.n is not None:
        return ("3d" if r.z is not None else "horizontal"), "prism"
    if r.z is not None:
        return "z", "settlement_pin"
    return "value", "convergence_chord"


def usable(axis: str, r: ParsedReading) -> bool:
    """Whether the row carries the numbers ``axis`` needs."""
    return {
        "z": r.z is not None,
        "value": r.value is not None,
        "horizontal": r.e is not None and r.n is not None,
        "3d": r.e is not None and r.n is not None and r.z is not None,
    }[axis]


class MonitoringService:
    """Operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MonitoringRepository(session)

    async def _audit(self, action: str, entity_id: uuid.UUID, user_id: str | None, details: dict[str, Any]) -> None:
        try:
            from app.core.audit import audit_log  # noqa: PLC0415

            uid = _uuid(user_id)
            await audit_log(
                self.session,
                action=action,
                entity_type="monitoring",
                entity_id=str(entity_id),
                user_id=str(uid) if uid else None,
                details=details,
            )
        except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
            logger.exception("monitoring: audit entry for %s failed", entity_id)

    # ── Profiles and settings ──────────────────────────────────────────────

    @staticmethod
    def _project_profile(row: MonitoringProfile) -> profile_lib.MonitoringProfile:
        return profile_lib.MonitoringProfile(
            key=f"project:{row.id}",
            name=row.name,
            source="project",
            thresholds=Thresholds(
                row.alert_mm, row.action_mm, row.alarm_mm, row.rate_alert, row.rate_action, row.rate_alarm
            ),
            reference=row.reference,
        )

    async def profiles(self, project_id: uuid.UUID, markets: list[str]) -> list[ProfileOut]:
        """Demo profile, then the active packs' profiles, then the project's own."""
        out = [_profile_out(profile_lib.DEMO_PROFILE)]
        out += [_profile_out(p) for p in profile_lib.pack_profiles_for(markets)]
        out += [_profile_out(self._project_profile(r)) for r in await self.repo.list_profiles(project_id)]
        return out

    async def create_profile(self, project_id: uuid.UUID, body: ProfileCreate, user_id: str) -> ProfileOut:
        row = MonitoringProfile(
            project_id=project_id,
            name=body.name,
            reference=body.reference,
            alert_mm=_dec(body.alert_mm),
            action_mm=_dec(body.action_mm),
            alarm_mm=_dec(body.alarm_mm),
            rate_alert=_dec(body.rate_alert),
            rate_action=_dec(body.rate_action),
            rate_alarm=_dec(body.rate_alarm),
            created_by=_uuid(user_id),
        )
        if not ordered(self._project_profile(row).thresholds):
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "Thresholds must rise from alert to action to alarm")
        await self.repo.add(row)
        await self._audit("create", row.id, user_id, {"profile": body.model_dump(mode="json")})
        return _profile_out(self._project_profile(row))

    async def _resolve(
        self, project_id: uuid.UUID, key: str, markets: list[str]
    ) -> profile_lib.MonitoringProfile | None:
        if not key:
            return None
        if key.startswith("project:"):
            row = await self.repo.get_profile(_uuid(key.split(":", 1)[1]) or uuid.uuid4())
            return self._project_profile(row) if row and row.project_id == project_id else None
        return profile_lib.builtin_profile(key, markets)

    async def active_profile(self, project_id: uuid.UUID, markets: list[str]) -> profile_lib.MonitoringProfile | None:
        """The project's profile; None when none is set or its pack is not an active market."""
        settings = await self.repo.settings(project_id)
        return await self._resolve(project_id, settings.profile_key if settings else "", markets)

    async def get_settings(self, project_id: uuid.UUID, markets: list[str]) -> SettingsOut:
        profile = await self.active_profile(project_id, markets)
        return SettingsOut(
            profile_key=profile.key if profile else "", profile=_profile_out(profile) if profile else None
        )

    async def set_settings(
        self, project_id: uuid.UUID, body: SettingsUpdate, user_id: str, markets: list[str]
    ) -> SettingsOut:
        if body.profile_key and await self._resolve(project_id, body.profile_key, markets) is None:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown threshold profile")
        row = await self.repo.settings(project_id)
        old = row.profile_key if row else ""
        if row is None:
            row = MonitoringSettings(project_id=project_id, profile_key=body.profile_key)
            await self.repo.add(row)
        else:
            row.profile_key = body.profile_key
            await self.session.flush()
        await self._audit("update", row.id, user_id, {"old": old, "new": body.profile_key})
        return await self.get_settings(project_id, markets)

    # ── Points ─────────────────────────────────────────────────────────────

    async def create_point(self, project_id: uuid.UUID, body: PointCreate, user_id: str) -> PointOut:
        if any(p.code == body.code for p in await self.repo.list_points(project_id)):
            raise _err(status.HTTP_409_CONFLICT, "A monitoring point with this id already exists")
        point = MonitoringPoint(
            project_id=project_id,
            code=body.code,
            name=body.name,
            point_type=body.point_type,
            axis=body.axis or DEFAULT_AXIS[body.point_type],
            location=body.location,
            created_by=_uuid(user_id),
        )
        await self.repo.add(point)
        await self._audit("create", point.id, user_id, {"point": body.model_dump(mode="json")})
        return self._point_out(point, [], [], None)

    async def get_point(self, point_id: uuid.UUID) -> MonitoringPoint:
        point = await self.repo.get_point(point_id)
        if point is None:
            raise not_found()
        return point

    async def update_point(
        self, point: MonitoringPoint, body: PointUpdate, user_id: str, markets: list[str]
    ) -> PointOut:
        changes = body.model_dump(exclude_unset=True)
        old = {k: getattr(point, k) for k in changes}
        for name, value in changes.items():
            if value is not None:
                setattr(point, name, value)
        await self.session.flush()
        await self._audit("update", point.id, user_id, {"old": old, "new": changes})
        return (await self._outs(point.project_id, markets, only=point.id))[0]

    async def delete_point(self, point: MonitoringPoint, user_id: str) -> None:
        await self._audit("delete", point.id, user_id, {"code": point.code})
        await self.repo.delete_point(point)

    # ── Evaluation ─────────────────────────────────────────────────────────

    async def _series(
        self, project_id: uuid.UUID, points: list[MonitoringPoint], thresholds: Thresholds
    ) -> dict[uuid.UUID, list[tuple[MonitoringReading, datetime, Evaluation]]]:
        by_point: dict[uuid.UUID, list[tuple[MonitoringReading, datetime]]] = {p.id: [] for p in points}
        for reading, at in await self.repo.readings(project_id, [p.id for p in points]):
            by_point[reading.point_id].append((reading, at))
        out: dict[uuid.UUID, list[tuple[MonitoringReading, datetime, Evaluation]]] = {}
        for p in points:
            rows = by_point[p.id]
            evals = evaluate(p.axis, [Reading(at, r.e, r.n, r.z, r.value) for r, at in rows], thresholds)
            out[p.id] = [(r, at, ev) for (r, at), ev in zip(rows, evals, strict=True)]
        return out

    def _point_out(
        self,
        point: MonitoringPoint,
        series: list[tuple[MonitoringReading, datetime, Evaluation]],
        alerts: list[MonitoringAlert],
        profile: profile_lib.MonitoringProfile | None,
    ) -> PointOut:
        first, last = (series[0], series[-1]) if series else (None, None)

        def shown(item: tuple[MonitoringReading, datetime, Evaluation] | None) -> float | None:
            if item is None:
                return None
            return _f(item[0].value if point.axis == "value" else item[0].z)

        if last is None or profile is None:
            level = "none"
        else:
            level = last[2].level
        fc = forecast([ev for _, _, ev in series], profile.thresholds) if profile is not None else None
        pending = any(a.acknowledged_at is None for a in alerts)
        return PointOut(
            id=point.id,
            project_id=point.project_id,
            code=point.code,
            name=point.name,
            point_type=point.point_type,  # type: ignore[arg-type]
            axis=point.axis,  # type: ignore[arg-type]
            location=point.location,
            epochs=len(series),
            baseline_at=first[1] if first else None,
            latest_at=last[1] if last else None,
            baseline_value=shown(first),
            latest_value=shown(last),
            displacement_mm=_f(last[2].displacement_mm) if last else None,
            rate_mm_day=_f(last[2].rate_mm_day) if last else None,
            level=level,  # type: ignore[arg-type]
            ack_state="pending" if pending else ("done" if alerts else "none"),
            forecast_level=(fc.level or "") if fc else "",
            forecast_days=fc.days if fc else None,
            forecast_rate_mm_day=fc.slope_mm_day if fc else None,
            forecast_approaching=fc.approaching if fc else False,
            forecast_epochs=fc.epochs if fc else 0,
            forecast_levels=[
                ForecastLevelOut(level=lf.level, limit_mm=lf.limit_mm, reached=lf.reached, days=lf.days)  # type: ignore[arg-type]
                for lf in (fc.levels if fc else ())
            ],
        )

    async def _outs(self, project_id: uuid.UUID, markets: list[str], only: uuid.UUID | None = None) -> list[PointOut]:
        profile = await self.active_profile(project_id, markets)
        points = [p for p in await self.repo.list_points(project_id) if only is None or p.id == only]
        series = await self._series(project_id, points, profile.thresholds if profile else Thresholds())
        alerts: dict[uuid.UUID, list[MonitoringAlert]] = {p.id: [] for p in points}
        for a in await self.repo.alerts(project_id):
            alerts.setdefault(a.point_id, []).append(a)
        return [self._point_out(p, series[p.id], alerts.get(p.id, []), profile) for p in points]

    async def list_points(self, project_id: uuid.UUID, markets: list[str]) -> list[PointOut]:
        return await self._outs(project_id, markets)

    async def detail(self, point: MonitoringPoint, markets: list[str]) -> PointDetail:
        profile = await self.active_profile(point.project_id, markets)
        series = (await self._series(point.project_id, [point], profile.thresholds if profile else Thresholds()))[
            point.id
        ]
        alerts = await self.repo.alerts(point.project_id, point.id)
        base = self._point_out(point, series, alerts, profile)
        risk_by_reading = {a.reading_id: a.risk_id for a in alerts if a.risk_id}
        return PointDetail(
            **base.model_dump(),
            profile_label=profile.name if profile else "",
            thresholds=_thresholds_out(profile.thresholds) if profile else None,
            series=[
                SeriesEntry(
                    at=at,
                    e=_f(r.e),
                    n=_f(r.n),
                    z=_f(r.z),
                    value=_f(r.value),
                    displacement_mm=_f(ev.displacement_mm),
                    rate_mm_day=_f(ev.rate_mm_day),
                    level=ev.level if profile else "none",  # type: ignore[arg-type]
                    risk_id=risk_by_reading.get(r.id),
                )
                for r, at, ev in series
            ],
            alerts=[_alert_out(a) for a in reversed(alerts)],
        )

    async def summary(self, project_id: uuid.UUID, markets: list[str]) -> MonitoringSummary:
        points = await self._outs(project_id, markets)
        count = {lvl: sum(1 for p in points if p.level == lvl) for lvl in ("alert", "action", "alarm")}
        epochs = await self.repo.list_epochs(project_id)
        return MonitoringSummary(
            points=len(points),
            ok=len(points) - sum(count.values()),
            unacknowledged=sum(1 for p in points if p.ack_state == "pending"),
            last_epoch=epochs[-1].observed_at if epochs else None,
            **count,
        )

    # ── Import ─────────────────────────────────────────────────────────────

    async def _plan(
        self, project_id: uuid.UUID, parsed: ParseResult
    ) -> tuple[dict[str, tuple[str, str]], list[ParsedReading], int, list[ImportProblem]]:
        """``(new point -> (axis, type), readings to add, identical readings skipped, row problems)``."""
        points = {p.code: p for p in await self.repo.list_points(project_id)}
        existing: dict[tuple[uuid.UUID, datetime], tuple[Any, ...]] = {
            (r.point_id, at): (r.e, r.n, r.z, r.value) for r, at in await self.repo.readings(project_id)
        }
        new: dict[str, tuple[str, str]] = {}
        accepted: list[ParsedReading] = []
        problems: list[ImportProblem] = []
        skipped = 0
        for r in parsed.readings:
            point = points.get(r.point)
            if point is not None:
                axis = point.axis
            else:
                axis = new.setdefault(r.point, infer_axis(r))[0]
            if not usable(axis, r):
                problems.append(
                    ImportProblem(
                        line=r.line,
                        point_id=r.point,
                        message=f"Point {r.point} is read along {axis} and the row has no {_NEED[axis]}.",
                    )
                )
                continue
            stored = existing.get((point.id, r.at)) if point is not None else None
            if stored is not None:
                if stored == (r.e, r.n, r.z, r.value):
                    skipped += 1
                else:
                    problems.append(
                        ImportProblem(
                            line=r.line,
                            point_id=r.point,
                            message="A different reading of this point already exists for that date.",
                        )
                    )
                continue
            accepted.append(r)
        # A code whose every row was rejected is not a point worth creating.
        kept = {r.point for r in accepted}
        return {c: v for c, v in new.items() if c in kept}, accepted, skipped, problems

    async def preview_readings(self, project_id: uuid.UUID, body: ReadingsImport) -> ReadingsPreview:
        parsed = self._parse(body)
        new, accepted, skipped, extra = await self._plan(project_id, parsed)
        known = {e.observed_at for e in await self.repo.list_epochs(project_id)}
        problems = _problems(parsed, extra)
        return ReadingsPreview(
            rows_read=parsed.rows_read,
            readings=len(accepted),
            new_points=list(new),
            epochs=sorted({r.at for r in accepted} - known),
            already_imported=skipped,
            problems=problems[:50],
            problem_count=len(problems),
        )

    @staticmethod
    def _parse(body: ReadingsImport) -> ParseResult:
        try:
            return parse_readings(body.text)
        except ValueError as exc:
            raise _err(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc

    async def import_readings(
        self,
        project_id: uuid.UUID,
        body: ReadingsImport,
        user_id: str,
        markets: list[str],
        locale: str = "en",
    ) -> ReadingsResult:
        parsed = self._parse(body)
        new, accepted, skipped, extra = await self._plan(project_id, parsed)
        problems = _problems(parsed, extra)
        uid = _uuid(user_id)
        points = {p.code: p for p in await self.repo.list_points(project_id)}
        for code, (axis, point_type) in new.items():
            point = MonitoringPoint(project_id=project_id, code=code, point_type=point_type, axis=axis, created_by=uid)
            await self.repo.add(point)
            points[code] = point
        epochs: dict[datetime, MonitoringEpoch] = {}
        epochs_added = 0
        added: dict[uuid.UUID, MonitoringReading] = {}
        for r in accepted:
            epoch = epochs.get(r.at) or await self.repo.epoch_at(project_id, r.at)
            if epoch is None:
                epoch = MonitoringEpoch(
                    project_id=project_id,
                    observed_at=r.at,
                    label=body.filename[:255],
                    source_filename=body.filename,
                    imported_by=uid,
                )
                await self.repo.add(epoch)
                epochs_added += 1
            epochs[r.at] = epoch
            row = MonitoringReading(
                project_id=project_id,
                point_id=points[r.point].id,
                epoch_id=epoch.id,
                e=r.e,
                n=r.n,
                z=r.z,
                value=r.value,
            )
            try:
                async with self.session.begin_nested():
                    await self.repo.add(row)
            except IntegrityError:
                problems.append(
                    ImportProblem(line=r.line, point_id=r.point, message="This point and date were just imported.")
                )
                continue
            added[row.id] = row
        alerts = await self._open_alerts(project_id, points, set(added), user_id, markets, locale)
        await self._audit(
            "import",
            project_id,
            user_id,
            {
                "file": body.filename,
                "readings": len(added),
                "points": list(new),
                "epochs": epochs_added,
                "alerts": [a.level for a in alerts],
            },
        )
        return ReadingsResult(
            rows_read=parsed.rows_read,
            readings_added=len(added),
            readings_skipped=skipped,
            new_points=list(new),
            epochs_added=epochs_added,
            alerts=[_alert_out(a) for a in alerts],
            problems=problems[:50],
            problem_count=len(problems),
        )

    # ── Alerts, notifications, risk drafts ─────────────────────────────────

    async def _open_alerts(
        self,
        project_id: uuid.UUID,
        points: dict[str, MonitoringPoint],
        new_reading_ids: set[uuid.UUID],
        user_id: str,
        markets: list[str],
        locale: str,
    ) -> list[MonitoringAlert]:
        profile = await self.active_profile(project_id, markets)
        if profile is None or profile.thresholds.is_empty() or not new_reading_ids:
            return []
        touched = [p for p in points.values()]
        series = await self._series(project_id, touched, profile.thresholds)
        opened: list[MonitoringAlert] = []
        for point in touched:
            for reading, at, ev in series[point.id]:
                if reading.id not in new_reading_ids or not ev.crossed or ev.displacement_mm is None:
                    continue
                alert = MonitoringAlert(
                    project_id=project_id,
                    point_id=point.id,
                    reading_id=reading.id,
                    level=ev.level,
                    displacement_mm=ev.displacement_mm,
                    rate_mm_day=ev.rate_mm_day,
                    observed_at=at,
                    profile_label=profile.name,
                    thresholds=profile.thresholds.as_json(),
                )
                await self.repo.add(alert)
                alert.notified = await self._notify(alert, point, user_id)
                if RANK[ev.level] >= RANK["action"]:
                    alert.risk_id = await self._risk_draft(alert, point, profile.name, user_id, locale)
                await self.session.flush()
                await self._audit(
                    "alert",
                    point.id,
                    user_id,
                    {"level": ev.level, "displacement_mm": str(ev.displacement_mm), "risk": alert.risk_id},
                )
                opened.append(alert)
        return opened

    async def _notify(self, alert: MonitoringAlert, point: MonitoringPoint, user_id: str) -> bool:
        try:
            from app.modules.notifications.service import NotificationService  # noqa: PLC0415
        except ImportError:  # pragma: no cover - the notifications module is optional
            return False
        recipients = {u for u in (await self.repo.project_owner(point.project_id), _uuid(user_id)) if u is not None}
        try:
            async with self.session.begin_nested():
                service = NotificationService(self.session)
                for recipient in sorted(recipients, key=str):
                    await service.create(
                        recipient,
                        f"monitoring_{alert.level}",
                        f"notifications.monitoring.{alert.level}.title",
                        entity_type="monitoring_point",
                        entity_id=str(point.id),
                        body_key="notifications.monitoring.crossed.body",
                        body_context={
                            "point": point.code,
                            "displacement": f"{alert.displacement_mm:.1f}",
                            "rate": "-" if alert.rate_mm_day is None else f"{alert.rate_mm_day:.2f}",
                        },
                        action_url="/survey/monitoring",
                        metadata={"alert_id": str(alert.id), "level": alert.level},
                    )
            return bool(recipients)
        except Exception:  # noqa: BLE001 - a failed notification must not undo the import
            logger.exception("monitoring: notification for %s failed", point.code)
            return False

    async def _risk_draft(
        self, alert: MonitoringAlert, point: MonitoringPoint, profile_name: str, user_id: str, locale: str
    ) -> str | None:
        try:
            from app.modules.risk.schemas import RiskCreate  # noqa: PLC0415
            from app.modules.risk.service import RiskService  # noqa: PLC0415
        except ImportError:  # pragma: no cover - the risk module is optional
            return None
        from app.core.validation.messages import translate  # noqa: PLC0415

        level = translate(f"monitoring.level.{alert.level}", locale=locale)
        rate = "-" if alert.rate_mm_day is None else f"{alert.rate_mm_day:.2f}"
        try:
            async with self.session.begin_nested():
                risk = await RiskService(self.session).create_risk(
                    RiskCreate(
                        project_id=alert.project_id,
                        title=translate("monitoring.risk.title", locale=locale, id=point.code, level=level)[:255],
                        description=translate(
                            "monitoring.risk.description",
                            locale=locale,
                            d=f"{alert.displacement_mm:.1f}",
                            r=rate,
                            profile=profile_name,
                        ),
                        category="safety",
                        probability=0.5 if alert.level == "action" else 0.8,
                        impact_severity="high" if alert.level == "action" else "critical",
                        status="identified",
                        metadata={
                            "source": "monitoring",
                            "draft": True,
                            "point_id": str(point.id),
                            "point_code": point.code,
                            "reading_id": str(alert.reading_id),
                            "alert_id": str(alert.id),
                            "rule_id": "MON-001",
                            "level": alert.level,
                        },
                    ),
                    user_id=user_id,
                )
            return str(risk.id)
        except Exception:  # noqa: BLE001 - a failed risk draft must not undo the import
            logger.exception("monitoring: risk draft for %s failed", point.code)
            return None

    async def acknowledge(
        self, point: MonitoringPoint, body: Acknowledge, user_id: str, markets: list[str]
    ) -> PointDetail:
        pending = [a for a in await self.repo.alerts(point.project_id, point.id) if a.acknowledged_at is None]
        if not pending:
            raise _err(status.HTTP_409_CONFLICT, "Nothing to acknowledge")
        uid = _uuid(user_id)
        name = await self.repo.user_name(uid)
        now = datetime.now(UTC)
        for a in pending:
            a.acknowledged_at, a.acknowledged_by, a.acknowledged_by_name, a.note = now, uid, name, body.note
        await self.session.flush()
        await self._audit("acknowledge", point.id, user_id, {"alerts": [str(a.id) for a in pending], "note": body.note})
        return await self.detail(point, markets)

    # ── Validation, report ─────────────────────────────────────────────────

    async def validate(self, project_id: uuid.UUID, markets: list[str], locale: str = "en") -> ValidationReportOut:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        points = await self._outs(project_id, markets)
        data = {
            "points": [
                {
                    "code": p.code,
                    "level": p.level,
                    "displacement_mm": p.displacement_mm,
                    "rate_mm_day": p.rate_mm_day,
                    "acknowledged": p.ack_state == "done",
                    "forecast_level": p.forecast_level,
                    "forecast_days": p.forecast_days,
                }
                for p in points
            ]
        }
        report = await validation_engine.validate(
            data=data,
            rule_sets=[MONITORING_RULE_SET],
            target_type="monitoring",
            target_id=str(project_id),
            project_id=str(project_id),
            metadata={"locale": locale},
        )
        failed = [r for r in report.results if not r.passed]
        return ValidationReportOut(
            status=str(getattr(report.status, "value", report.status)),
            error_count=len(report.errors),
            warning_count=len(report.warnings),
            info_count=len(report.infos),
            findings=[
                Finding(
                    rule_id=r.rule_id,
                    severity=str(getattr(r.severity, "value", r.severity)),
                    message=r.message,
                    suggestion=r.suggestion,
                    element_ref=r.element_ref,
                )
                for r in failed
            ],
        )

    async def report_pdf(self, project_id: uuid.UUID, markets: list[str], locale: str = "en") -> bytes:
        from app.modules.monitoring.report_pdf import build_alarm_report  # noqa: PLC0415

        profile = await self.active_profile(project_id, markets)
        return build_alarm_report(
            await self._outs(project_id, markets),
            project_name=await self.repo.project_name(project_id),
            crs_label=await self.repo.project_crs_label(project_id),
            profile=_profile_out(profile) if profile else None,
            findings=(await self.validate(project_id, markets, locale)).findings,
            locale=locale,
        )

    # ── Riverside Yard demo ────────────────────────────────────────────────

    async def load_riverside_demo(
        self, project_id: uuid.UUID, user_id: str, markets: list[str], locale: str = "en", epochs: int = 0
    ) -> list[PointOut]:
        """The demo profile, points MP-01 and MP-02, and optionally the lesson files (3 or 4 epochs).

        Idempotent: what exists stays, identical readings are skipped. With ``epochs=0`` the
        learner imports the files by hand (lessons 1 and 3).
        """
        settings = await self.repo.settings(project_id)
        if settings is None or not settings.profile_key:
            await self.set_settings(project_id, SettingsUpdate(profile_key=profile_lib.DEMO_KEY), user_id, markets)
        known = {p.code for p in await self.repo.list_points(project_id)}
        for code, name in DEMO_POINTS:
            if code not in known:
                await self.create_point(
                    project_id,
                    PointCreate(code=code, name=name, point_type="settlement_pin", location="Pit-edge wall"),
                    user_id,
                )
        files = {3: ["monitoring_epochs_1-3.csv"], 4: ["monitoring_epochs_1-3.csv", "monitoring_epoch_4.csv"]}
        for name in files.get(epochs, []):
            await self.import_readings(
                project_id,
                ReadingsImport(text=(DEMO_DIR / name).read_text(encoding="utf-8"), filename=name),
                user_id,
                markets,
                locale,
            )
        return await self.list_points(project_id, markets)
