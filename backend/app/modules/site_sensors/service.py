# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors service​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: devices, ingest, limits, alerts, maturity and formwork strikes.

A reading is checked against the device's own limit, else the limit the
project's country sets for that kind (``app.core.site_monitoring``). One
episode above the limit is one open alert; it stays open until a person
acknowledges it. A concrete sensor's maturity is recomputed on ingest and, when
the mix curve says the pour has reached the strike strength, the planned
formwork strikes on that pour are released and their schedule activity is
named in the event.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.site_monitoring import sensor_limit
from app.modules.site_sensors.maturity import (
    hours_to_strength,
    maturity_for_strength,
    nurse_saul,
    strength_from_maturity,
)
from app.modules.site_sensors.models import ConcreteMix, FormworkStrip, SensorAlert, SensorDevice
from app.modules.site_sensors.repository import SiteSensorsRepository
from app.modules.site_sensors.schemas import DEFAULT_UNITS, DeviceCreate, DeviceUpdate, MixCreate, StripCreate

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "oes_"
#: Raw readings younger than this stay raw; older ones are folded into hourly rows.
RAW_RETENTION_DAYS = 30

EVENT_LIMIT_EXCEEDED = "site_sensors.limit.exceeded"
EVENT_OFFLINE = "site_sensors.device.offline"
EVENT_STRENGTH_REACHED = "site_sensors.strength.reached"
EVENT_ALERT_ACKNOWLEDGED = "site_sensors.alert.acknowledged"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class SiteSensorsService:
    """Business logic of the site sensors module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SiteSensorsRepository(session)

    # ── Devices ─────────────────────────────────────────────────────────

    async def create_device(self, data: DeviceCreate) -> SensorDevice:
        values = data.model_dump()
        values["unit"] = values["unit"] or DEFAULT_UNITS.get(data.kind, "")
        values["country_code"] = (values["country_code"] or "").upper()
        device = SensorDevice(**values)
        self.session.add(device)
        await self.session.flush()
        return device

    async def get_device(self, device_id: uuid.UUID) -> SensorDevice:
        device = await self.session.get(SensorDevice, device_id)
        if device is None:
            raise LookupError("device_not_found")
        return device

    async def update_device(self, device_id: uuid.UUID, data: DeviceUpdate) -> SensorDevice:
        device = await self.get_device(device_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(device, k, v.upper() if k == "country_code" and isinstance(v, str) else v)
        await self.session.flush()
        return device

    async def issue_token(self, device_id: uuid.UUID) -> str:
        """A new ingest token for the device; the previous one stops working."""
        device = await self.get_device(device_id)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        device.token_hash = _hash(token)
        device.token_prefix = token[:10]
        await self.session.flush()
        return token

    async def authenticate(self, token: str | None) -> SensorDevice | None:
        if not token or not token.startswith(TOKEN_PREFIX):
            return None
        device = await self.repo.device_by_token_hash(_hash(token))
        return device if device is not None and device.active else None

    # ── Mixes and strikes ───────────────────────────────────────────────

    async def create_mix(self, data: MixCreate) -> ConcreteMix:
        mix = ConcreteMix(**data.model_dump())
        self.session.add(mix)
        await self.session.flush()
        return mix

    async def list_mixes(self, project_id: uuid.UUID | None) -> list[ConcreteMix]:
        stmt = select(ConcreteMix).order_by(ConcreteMix.code)
        if project_id is not None:
            stmt = stmt.where((ConcreteMix.project_id == project_id) | (ConcreteMix.project_id.is_(None)))
        return list((await self.session.execute(stmt)).scalars())

    async def create_strip(self, data: StripCreate) -> FormworkStrip:
        device = await self.get_device(data.device_id)
        if device.kind != "concrete_maturity":
            raise ValueError("strip_needs_concrete_sensor")
        target = data.target_strength_mpa
        if target is None:
            mix = await self.session.get(ConcreteMix, device.mix_id) if device.mix_id else None
            target = mix.strip_strength_mpa if mix else None
        if target is None:
            raise ValueError("target_strength_required")
        strip = FormworkStrip(
            project_id=device.project_id,
            device_id=device.id,
            element=data.element or device.pour_ref,
            schedule_activity_id=data.schedule_activity_id or device.schedule_activity_id,
            target_strength_mpa=target,
            planned_at=data.planned_at,
        )
        self.session.add(strip)
        await self.session.flush()
        est = await self.maturity(device.id)
        if est.get("strength_mpa") is not None and Decimal(str(est["strength_mpa"])) >= target:
            strip.released_at = datetime.now(UTC)
            strip.status = "released"
            await self.session.flush()
        return strip

    async def list_strips(self, project_id: uuid.UUID) -> list[FormworkStrip]:
        stmt = select(FormworkStrip).where(FormworkStrip.project_id == project_id).order_by(FormworkStrip.created_at)
        return list((await self.session.execute(stmt)).scalars())

    async def strike(self, strip_id: uuid.UUID, struck_at: datetime | None = None) -> FormworkStrip:
        """Record the strike with the strength estimated at that moment.

        A strike before the target strength is recorded, not refused: the site
        may have reasons (back-propping, a test cube result) the sensor does not
        know. The validation rule flags it for a person to confirm.
        """
        strip = await self.session.get(FormworkStrip, strip_id)
        if strip is None:
            raise LookupError("strip_not_found")
        when = _aware(struck_at or datetime.now(UTC))
        est = await self.maturity(strip.device_id, until=when)
        strip.struck_at = when
        if est.get("strength_mpa") is not None:
            strip.strength_at_strike_mpa = Decimal(str(est["strength_mpa"])).quantize(Decimal("0.01"))
        strip.status = "struck"
        await self.session.flush()
        return strip

    # ── Ingest ──────────────────────────────────────────────────────────

    async def _country(self, device: SensorDevice) -> str | None:
        if device.country_code:
            return device.country_code
        from app.modules.projects.models import Project

        project = await self.session.get(Project, device.project_id)
        return (project.country_code or None) if project else None

    async def limit_of(self, device: SensorDevice, at: datetime | None = None) -> tuple[float | None, str]:
        """The limit that applies to a device and where it comes from."""
        if device.limit_value is not None:
            return float(device.limit_value), "device"
        lim = sensor_limit(await self._country(device), device.kind, at.timetz().replace(tzinfo=None) if at else None)
        if lim is None:
            return None, ""
        return float(lim.value), lim.source

    async def ingest(self, device: SensorDevice, readings: list[tuple[datetime, float]]) -> dict[str, Any]:
        """Store readings, raise or update alerts, refresh maturity. Returns a short report."""
        rows = sorted(((_aware(t), float(v)) for t, v in readings), key=lambda r: r[0])
        await self.repo.insert_readings(device.id, rows)
        last_t, last_v = rows[-1]
        if device.last_seen_at is None or last_t >= _aware(device.last_seen_at):
            device.last_seen_at = last_t
            device.last_value = last_v
        offline = await self.repo.open_alert(device.id, "offline")
        if offline is not None:
            offline.status = "closed"
        exceeded = 0
        if device.kind != "concrete_maturity":
            for t, v in rows:
                limit, source = await self.limit_of(device, t)
                if limit is not None and v > limit:
                    exceeded += 1
                    await self._raise_exceedance(device, t, v, limit, source)
        await self.session.flush()
        released = 0
        if device.kind == "concrete_maturity":
            released = await self._check_strength(device)
        return {"accepted": len(rows), "exceedances": exceeded, "strips_released": released}

    async def _raise_exceedance(self, device: SensorDevice, t: datetime, v: float, limit: float, source: str) -> None:
        alert = await self.repo.open_alert(device.id, "exceedance")
        if alert is not None:
            if alert.value is None or v > alert.value:
                alert.value = v
            return
        alert = SensorAlert(
            project_id=device.project_id,
            device_id=device.id,
            kind="exceedance",
            raised_at=t,
            value=v,
            limit_value=limit,
            limit_source=source[:300],
        )
        self.session.add(alert)
        await self.session.flush()
        event_bus.publish_detached(
            EVENT_LIMIT_EXCEEDED,
            {
                "alert_id": str(alert.id),
                "device_id": str(device.id),
                "project_id": str(device.project_id),
                "kind": device.kind,
                "value": v,
                "limit": limit,
            },
            source_module="site_sensors",
        )
        await self._notify(
            device, "exceedance", {"device": device.code, "value": f"{v:g}", "limit": f"{limit:g}", "unit": device.unit}
        )

    async def _notify(self, device: SensorDevice, kind: str, context: dict[str, Any]) -> None:
        try:
            from app.modules.notifications.service import NotificationService
            from app.modules.projects.models import Project

            project = await self.session.get(Project, device.project_id)
            if project is None or project.owner_id is None:
                return
            await NotificationService(self.session).create(
                user_id=project.owner_id,
                notification_type="info" if kind == "strength_reached" else "warning",
                title_key=f"notifications.site_sensors_{kind}_title",
                body_key=f"notifications.site_sensors_{kind}_body",
                body_context=context,
                entity_type="site_sensor",
                entity_id=str(device.id),
                action_url=f"/projects/{device.project_id}/site-sensors",
            )
        except Exception:
            logger.debug("site sensor notification skipped", exc_info=True)

    # ── Maturity ────────────────────────────────────────────────────────

    async def maturity(self, device_id: uuid.UUID, until: datetime | None = None) -> dict[str, Any]:
        """Maturity, estimated strength and hours to the strike strength of a concrete sensor."""
        device = await self.get_device(device_id)
        mix = await self.session.get(ConcreteMix, device.mix_id) if device.mix_id else None
        since = _aware(device.cast_at) if device.cast_at else None
        hourly = await self.repo.hourly(device.id, since=since, until=until)
        raw = await self.repo.raw(device.id, since=since, until=until)
        temps = sorted([(_aware(h["hour"]), float(h["avg"])) for h in hourly] + [(_aware(t), v) for t, v in raw])
        datum = float(mix.datum_temp_c) if mix else -10.0
        series = nurse_saul(temps, datum)
        m_now = series[-1][1] if series else 0.0
        out: dict[str, Any] = {
            "device_id": str(device.id),
            "mix_id": str(mix.id) if mix else None,
            "datum_temp_c": datum,
            "maturity_c_h": round(m_now, 1),
            "strength_mpa": None,
            "target_strength_mpa": None,
            "hours_to_target": None,
            "series": [
                {"t": t.isoformat(), "maturity": round(m, 1), "temp": temp}
                for (t, m), (_, temp) in list(zip(series, temps, strict=True))[-200:]
            ],
        }
        if mix is None:
            return out
        a, b = float(mix.curve_a), float(mix.curve_b)
        out["strength_mpa"] = round(strength_from_maturity(m_now, a, b), 2)
        target = await self._target(device, mix)
        if target is not None:
            out["target_strength_mpa"] = float(target)
            need = maturity_for_strength(float(target), a, b)
            if need is not None:
                out["target_maturity_c_h"] = round(need, 1)
                hrs = hours_to_strength(series, need)
                out["hours_to_target"] = round(hrs, 1) if hrs is not None else None
        return out

    async def _target(self, device: SensorDevice, mix: ConcreteMix) -> Decimal | None:
        stmt = select(FormworkStrip.target_strength_mpa).where(
            FormworkStrip.device_id == device.id, FormworkStrip.status != "struck"
        )
        pending = [t for t in (await self.session.execute(stmt)).scalars() if t is not None]
        return min(pending) if pending else mix.strip_strength_mpa

    async def _check_strength(self, device: SensorDevice) -> int:
        est = await self.maturity(device.id)
        strength = est.get("strength_mpa")
        if strength is None:
            return 0
        stmt = select(FormworkStrip).where(FormworkStrip.device_id == device.id, FormworkStrip.status == "planned")
        released = 0
        now = datetime.now(UTC)
        for strip in (await self.session.execute(stmt)).scalars():
            if Decimal(str(strength)) >= strip.target_strength_mpa:
                strip.status = "released"
                strip.released_at = now
                released += 1
                event_bus.publish_detached(
                    EVENT_STRENGTH_REACHED,
                    {
                        "device_id": str(device.id),
                        "project_id": str(device.project_id),
                        "strip_id": str(strip.id),
                        "schedule_activity_id": str(strip.schedule_activity_id) if strip.schedule_activity_id else None,
                        "strength_mpa": strength,
                        "target_mpa": float(strip.target_strength_mpa),
                    },
                    source_module="site_sensors",
                )
        target = est.get("target_strength_mpa")
        if (
            target is not None
            and strength >= target
            and await self.repo.any_alert(device.id, "strength_reached") is None
        ):
            self.session.add(
                SensorAlert(
                    project_id=device.project_id,
                    device_id=device.id,
                    kind="strength_reached",
                    raised_at=now,
                    value=strength,
                    limit_value=target,
                    limit_source="mix",
                )
            )
            await self._notify(
                device,
                "strength_reached",
                {"device": device.code, "pour": device.pour_ref, "strength": f"{strength:g}"},
            )
        await self.session.flush()
        return released

    # ── Readings, alerts, offline ───────────────────────────────────────

    async def readings(self, device_id: uuid.UUID, since: datetime | None, until: datetime | None) -> dict[str, Any]:
        """Raw readings in the window plus the hourly rows for the part already folded."""
        await self.get_device(device_id)
        return {
            "raw": [{"t": t.isoformat(), "v": v} for t, v in await self.repo.raw(device_id, since, until)][-5000:],
            "hourly": [{**h, "hour": h["hour"].isoformat()} for h in await self.repo.hourly(device_id, since, until)][
                -5000:
            ],
        }

    async def downsample(self, older_than_days: int = RAW_RETENTION_DAYS) -> int:
        return await self.repo.fold_into_hourly(datetime.now(UTC) - timedelta(days=older_than_days))

    async def sweep_offline(self, project_id: uuid.UUID | None = None, now: datetime | None = None) -> int:
        """Open an offline alert for every active device silent longer than its window."""
        now = now or datetime.now(UTC)
        opened = 0
        for device in await self.repo.devices(project_id):
            if not device.active or device.last_seen_at is None:
                continue
            if now - _aware(device.last_seen_at) <= timedelta(minutes=device.offline_after_minutes):
                continue
            if await self.repo.open_alert(device.id, "offline") is not None:
                continue
            self.session.add(
                SensorAlert(
                    project_id=device.project_id,
                    device_id=device.id,
                    kind="offline",
                    raised_at=now,
                    value=None,
                    limit_value=float(device.offline_after_minutes),
                    limit_source="device",
                )
            )
            opened += 1
            event_bus.publish_detached(
                EVENT_OFFLINE,
                {"device_id": str(device.id), "project_id": str(device.project_id)},
                source_module="site_sensors",
            )
        await self.session.flush()
        return opened

    async def acknowledge(self, alert_id: uuid.UUID, user_id: uuid.UUID | str, note: str = "") -> SensorAlert:
        alert = await self.session.get(SensorAlert, alert_id)
        if alert is None:
            raise LookupError("alert_not_found")
        if alert.status == "open":
            alert.status = "acknowledged"
            alert.acknowledged_at = datetime.now(UTC)
            alert.acknowledged_by = uuid.UUID(str(user_id))
            alert.note = note or alert.note
            await self.session.flush()
            event_bus.publish_detached(
                EVENT_ALERT_ACKNOWLEDGED,
                {"alert_id": str(alert.id), "project_id": str(alert.project_id), "kind": alert.kind},
                source_module="site_sensors",
            )
        return alert

    async def link(self, alert_id: uuid.UUID, links: dict[str, uuid.UUID | None]) -> SensorAlert:
        alert = await self.session.get(SensorAlert, alert_id)
        if alert is None:
            raise LookupError("alert_not_found")
        for k, v in links.items():
            if v is not None:
                setattr(alert, k, v)
        await self.session.flush()
        return alert

    # ── Summary and rules ───────────────────────────────────────────────

    async def summary(self, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Numbers for the sensor alerts dashboard widget."""
        await self.sweep_offline(project_id)
        devices = await self.repo.devices(project_id)
        alerts = await self.repo.alerts(project_id, status="open", limit=500)
        by_kind: dict[str, int] = {}
        for a in alerts:
            by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
        offline_ids = {a.device_id for a in alerts if a.kind == "offline"}
        pours = []
        for d in devices:
            if d.kind == "concrete_maturity":
                est = await self.maturity(d.id)
                est.pop("series", None)
                pours.append({"code": d.code, "pour_ref": d.pour_ref, **est})
        return {
            "devices": len(devices),
            "online": len([d for d in devices if d.active and d.id not in offline_ids and d.last_seen_at]),
            "open_alerts": len(alerts),
            "open_by_kind": by_kind,
            "pours": pours,
            "latest_alerts": [
                {
                    "id": str(a.id),
                    "kind": a.kind,
                    "device_id": str(a.device_id),
                    "raised_at": a.raised_at.isoformat(),
                    "value": a.value,
                    "limit": a.limit_value,
                }
                for a in alerts[:5]
            ],
        }

    async def validation_payload(self, project_id: uuid.UUID) -> dict[str, Any]:
        await self.sweep_offline(project_id)
        devices = {d.id: d for d in await self.repo.devices(project_id)}
        alerts = await self.repo.alerts(project_id, limit=1000)
        strips = await self.list_strips(project_id)
        return {
            "devices": [
                {
                    "id": str(d.id),
                    "code": d.code,
                    "active": d.active,
                    "offline": any(a.device_id == d.id and a.kind == "offline" and a.status == "open" for a in alerts),
                }
                for d in devices.values()
            ],
            "exceedances": [
                {
                    "id": str(a.id),
                    "device": devices[a.device_id].code if a.device_id in devices else "",
                    "status": a.status,
                    "value": a.value,
                    "limit": a.limit_value,
                }
                for a in alerts
                if a.kind == "exceedance"
            ],
            "strips": [
                {
                    "id": str(s.id),
                    "element": s.element,
                    "struck": s.struck_at is not None,
                    "target_mpa": str(s.target_strength_mpa),
                    "strength_at_strike_mpa": str(s.strength_at_strike_mpa)
                    if s.strength_at_strike_mpa is not None
                    else None,
                }
                for s in strips
            ],
        }
