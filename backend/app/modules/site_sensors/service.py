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
from app.core.site_monitoring import limit_grading, night_noise_by_ordinance, sensor_limit
from app.modules.integrations.validators import build_sensor_link_payload
from app.modules.site_sensors.analysis import reading_stats, rolling_mean, sparkline
from app.modules.site_sensors.evidence import bim_link_rows, evidence_rows
from app.modules.site_sensors.maturity import (
    DEFAULT_DATUM_C,
    fit_log_curve,
    hours_to_strength,
    hours_to_target_range,
    maturity_for_strength,
    maturity_series,
    strength_estimate,
)
from app.modules.site_sensors.models import (
    CalibrationPoint,
    ConcreteMix,
    FormworkStrip,
    ReadingAudit,
    SensorAlert,
    SensorDevice,
)
from app.modules.site_sensors.repository import SiteSensorsRepository
from app.modules.site_sensors.schemas import (
    DEFAULT_UNITS,
    CalibrationPointIn,
    DeviceCreate,
    DeviceUpdate,
    MixCreate,
    MixUpdate,
    ReadingIn,
    StripCreate,
    check_limits,
)

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "oes_"
#: Raw readings younger than this stay raw; older ones are folded into hourly rows.
RAW_RETENTION_DAYS = 30
#: Kinds whose limit is a mean over a window rather than a single reading.
ROLLING_MEAN_HOURS = {"dust_pm10": 24.0}
#: Countries that measure in US customary units; the store stays SI.
IMPERIAL_COUNTRIES = frozenset({"US", "LR", "MM"})

EVENT_LIMIT_EXCEEDED = "site_sensors.limit.exceeded"
EVENT_OFFLINE = "site_sensors.device.offline"
EVENT_STRENGTH_REACHED = "site_sensors.strength.reached"
EVENT_ALERT_ACKNOWLEDGED = "site_sensors.alert.acknowledged"
EVENT_READING_CHANGED = "site_sensors.reading.changed"
#: Readings a person may change; device readings are the instrument's record and stay as sent.
EDITABLE_SOURCES = frozenset({"manual", "import"})


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
            if v is None and k in ("record_only", "limit_note", "unit", "name"):
                continue
            setattr(device, k, v.upper() if k == "country_code" and isinstance(v, str) else v)
        err = check_limits(device.kind, device.unit, device.limit_value, device.lower_limit, bool(device.record_only))
        if err:
            raise ValueError(err)
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

    async def update_mix(self, mix_id: uuid.UUID, data: MixUpdate) -> ConcreteMix:
        """Change a mix by hand: its datum temperature, method constants, curve or strike strength."""
        mix = await self.get_mix(mix_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            if v is None and k not in ("strip_strength_mpa", "notes"):
                continue
            setattr(mix, k, v)
        await self.session.flush()
        return mix

    async def get_mix(self, mix_id: uuid.UUID) -> ConcreteMix:
        mix = await self.session.get(ConcreteMix, mix_id)
        if mix is None:
            raise LookupError("mix_not_found")
        return mix

    async def set_calibration(self, mix_id: uuid.UUID, points: list[CalibrationPointIn]) -> ConcreteMix:
        """Replace the mix's calibration table and refit ``a``, ``b`` and R² from it.

        With fewer than two usable points the curve keeps its entered ``a`` and
        ``b`` and the fit fields are cleared; the calibration rules say why.
        """
        mix = await self.get_mix(mix_id)
        rows = [
            CalibrationPoint(
                mix_id=mix.id,
                maturity_index=p.maturity_index,
                strength_mpa=p.strength_mpa,
                age_hours=p.age_hours,
                note=p.note,
            )
            for p in points
        ]
        await self.repo.replace_calibration(mix.id, rows)
        fit = fit_log_curve([(p.maturity_index, float(p.strength_mpa)) for p in points])
        if fit is None:
            mix.fit_r2 = None
            mix.calibrated_min = None
            mix.calibrated_max = None
        else:
            a, b, r2 = fit
            if b > 0:
                mix.curve_a = Decimal(str(round(a, 4)))
                mix.curve_b = Decimal(str(round(b, 4)))
            mix.fit_r2 = round(r2, 4)
            mix.calibrated_min = min(p.maturity_index for p in points)
            mix.calibrated_max = max(p.maturity_index for p in points)
        await self.session.flush()
        return mix

    async def list_mixes(self, project_id: uuid.UUID | None) -> list[ConcreteMix]:
        stmt = select(ConcreteMix).order_by(ConcreteMix.code)
        if project_id is not None:
            stmt = stmt.where((ConcreteMix.project_id == project_id) | (ConcreteMix.project_id.is_(None)))
        else:
            # Without a project the caller has proven access to, only shared mixes are listed.
            stmt = stmt.where(ConcreteMix.project_id.is_(None))
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
            bim_model_id=data.bim_model_id or device.bim_model_id,
            bim_element_id=data.bim_element_id or device.bim_element_id,
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

    async def strike(
        self,
        strip_id: uuid.UUID,
        struck_at: datetime | None = None,
        reason: str = "",
        user_id: uuid.UUID | str | None = None,
    ) -> FormworkStrip:
        """Record the strike with the strength estimated at that moment, and who struck.

        A strike before the target strength is allowed only with a reason (a
        cube result, back-propping): the site may know what the sensor does not.
        Without one it is refused with ``strike_reason_required``.
        """
        strip = await self.session.get(FormworkStrip, strip_id)
        if strip is None:
            raise LookupError("strip_not_found")
        when = _aware(struck_at or datetime.now(UTC))
        est = await self.maturity(strip.device_id, until=when)
        strength = est.get("strength_mpa")
        below = strength is None or Decimal(str(strength)) < strip.target_strength_mpa
        reason = (reason or "").strip()
        if below and not reason:
            raise ValueError("strike_reason_required")
        strip.struck_at = when
        if strength is not None:
            strip.strength_at_strike_mpa = Decimal(str(strength)).quantize(Decimal("0.01"))
        strip.strike_reason = reason or None
        strip.struck_by = uuid.UUID(str(user_id)) if user_id else None
        strip.status = "struck"
        await self.session.flush()
        from app.modules.site_sensors.events import EVENT_STRIP_STRUCK

        event_bus.publish_detached(
            EVENT_STRIP_STRUCK,
            {
                "strip_id": str(strip.id),
                "device_id": str(strip.device_id),
                "project_id": str(strip.project_id),
                "element": strip.element,
                "struck_at": when.isoformat(),
                "strength_mpa": float(strip.strength_at_strike_mpa)
                if strip.strength_at_strike_mpa is not None
                else None,
                "target_mpa": float(strip.target_strength_mpa),
            },
            source_module="site_sensors",
        )
        return strip

    # ── Ingest ──────────────────────────────────────────────────────────

    async def _country(self, device: SensorDevice) -> str | None:
        if device.country_code:
            return device.country_code
        from app.modules.projects.models import Project

        project = await self.session.get(Project, device.project_id)
        return (project.country_code or None) if project else None

    async def limit_of(
        self, device: SensorDevice, at: datetime | None = None, frequency_hz: float | None = None
    ) -> tuple[float | None, str]:
        """The upper limit that applies to a device and where it comes from."""
        if device.record_only:
            return None, ""
        if device.limit_value is not None:
            return float(device.limit_value), "device"
        lim = sensor_limit(
            await self._country(device),
            device.kind,
            at.timetz().replace(tzinfo=None) if at else None,
            zone=device.noise_zone or None,
            building_class=device.building_class or None,
            frequency_hz=frequency_hz,
            band=device.frequency_band or None,
        )
        if lim is None:
            return None, ""
        return float(lim.value), lim.source

    async def describe_limit(self, device: SensorDevice, at: datetime | None = None) -> dict[str, Any]:
        """The limit shown next to a device now, its source text, and whether a local ordinance sets the night one."""
        value, source = await self.limit_of(device, at or datetime.now(UTC))
        country = await self._country(device)
        country_limit, country_source = None, ""
        if device.limit_value is not None and device.kind != "custom":
            country_limit, country_source = await self.country_limit_of(device, at or datetime.now(UTC))
        return {
            "effective_limit": value,
            "limit_source": source,
            "country_limit": country_limit,
            "country_limit_source": country_source,
            "night_limit_by_ordinance": device.kind == "noise"
            and device.limit_value is None
            and night_noise_by_ordinance(country),
        }

    async def country_limit_of(self, device: SensorDevice, at: datetime | None = None) -> tuple[float | None, str]:
        """The limit the country data would set for this device, ignoring the device's own figure."""
        lim = sensor_limit(
            await self._country(device),
            device.kind,
            at.timetz().replace(tzinfo=None) if at else None,
            zone=device.noise_zone or None,
            building_class=device.building_class or None,
            band=device.frequency_band or None,
        )
        return (None, "") if lim is None else (float(lim.value), lim.source)

    def window_of(self, device: SensorDevice) -> float | None:
        """Hours of the rolling mean a device is checked on, or None for single readings."""
        return device.rolling_mean_hours or ROLLING_MEAN_HOURS.get(device.kind)

    async def ingest(
        self,
        device: SensorDevice,
        readings: list[tuple[datetime, float]],
        frequencies: dict[datetime, float] | None = None,
        *,
        source: str = "device",
        entered_by: uuid.UUID | None = None,
        notes: dict[datetime, str] | None = None,
    ) -> dict[str, Any]:
        """Store readings, raise or update alerts, refresh maturity. Returns a short report.

        Dust is compared as its 24 hour rolling mean, as the PM10 limit is
        written, and any device with its own window likewise; vibration against
        the limit at the reading's dominant frequency. A reading below the
        device's lower limit is an exceedance as well.
        """
        rows = sorted(((_aware(t), float(v)) for t, v in readings), key=lambda r: r[0])
        freq = {_aware(t): f for t, f in (frequencies or {}).items() if f}
        await self.repo.insert_readings(
            device.id,
            rows,
            freq,
            source=source,
            entered_by=entered_by,
            notes={_aware(t): n for t, n in (notes or {}).items() if n},
        )
        last_t, last_v = rows[-1]
        if device.last_seen_at is None or last_t >= _aware(device.last_seen_at):
            device.last_seen_at = last_t
            device.last_value = last_v
        offline = await self.repo.open_alert(device.id, "offline")
        if offline is not None:
            offline.status = "closed"
        exceeded = await self._check_limits(device, rows, freq)
        await self.session.flush()
        released = 0
        if device.kind == "concrete_maturity":
            released = await self._check_strength(device)
        return {"accepted": len(rows), "exceedances": exceeded, "strips_released": released}

    async def _check_limits(
        self, device: SensorDevice, rows: list[tuple[datetime, float]], freq: dict[datetime, float]
    ) -> int:
        """Raise or extend the exceedance alert for every reading past a limit; returns how many were."""
        if device.kind == "concrete_maturity" or device.record_only or not rows:
            return 0
        window = self.window_of(device)
        history: list[tuple[datetime, float]] = []
        if window:
            since = rows[0][0] - timedelta(hours=window)
            history = [(_aware(t), v) for t, v in await self.repo.raw(device.id, since=since, until=rows[-1][0])]
        lower = float(device.lower_limit) if device.lower_limit is not None else None
        exceeded = 0
        for t, raw_v in rows:
            v = raw_v
            if window:
                mean = rolling_mean(history, t, window)
                v = round(mean, 2) if mean is not None else raw_v
            limit, source = await self.limit_of(device, t, freq.get(t))
            if limit is not None and v > limit:
                exceeded += 1
                await self._raise_exceedance(device, t, v, limit, source)
            elif lower is not None and v < lower:
                exceeded += 1
                await self._raise_exceedance(device, t, v, lower, "device", below=True)
        return exceeded

    async def _raise_exceedance(
        self, device: SensorDevice, t: datetime, v: float, limit: float, source: str, *, below: bool = False
    ) -> None:
        if source == "device" and device.limit_note:
            source = device.limit_note
        alert = await self.repo.open_alert(device.id, "exceedance")
        if alert is not None:
            was_below = alert.value is not None and alert.limit_value is not None and alert.value < alert.limit_value
            if alert.value is None or (was_below == below and (v < alert.value if below else v > alert.value)):
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
        datum = float(mix.datum_temp_c) if mix else DEFAULT_DATUM_C
        method = mix.method if mix and mix.method else "nurse_saul"
        series = maturity_series(
            temps,
            method,
            datum,
            float(mix.activation_energy_kj_mol) if mix else 40.0,
            float(mix.reference_temp_c) if mix else 20.0,
        )
        m_now = series[-1][1] if series else 0.0
        out: dict[str, Any] = {
            "device_id": str(device.id),
            "mix_id": str(mix.id) if mix else None,
            "method": method,
            "index_unit": "h" if method == "equivalent_age" else "c_h",
            "datum_temp_c": datum,
            "activation_energy_kj_mol": float(mix.activation_energy_kj_mol) if mix else None,
            "reference_temp_c": float(mix.reference_temp_c) if mix else None,
            "maturity_c_h": round(m_now, 1),
            "strength_mpa": None,
            "strength_status": None,
            "calibrated_min": mix.calibrated_min if mix else None,
            "calibrated_max": mix.calibrated_max if mix else None,
            "fit_r2": mix.fit_r2 if mix else None,
            "target_strength_mpa": None,
            "hours_to_target": None,
            "hours_to_target_range": None,
            "series": [
                {"t": t.isoformat(), "maturity": round(m, 1), "temp": temp}
                for (t, m), (_, temp) in list(zip(series, temps, strict=True))[-200:]
            ],
        }
        if mix is None:
            return out
        a, b = float(mix.curve_a), float(mix.curve_b)
        out["strength_mpa"], out["strength_status"] = strength_estimate(
            m_now, a, b, mix.calibrated_min, mix.calibrated_max
        )
        target = await self._target(device, mix)
        if target is not None:
            out["target_strength_mpa"] = float(target)
            need = maturity_for_strength(float(target), a, b)
            if need is not None:
                out["target_maturity_c_h"] = round(need, 1)
                hrs = hours_to_strength(series, need)
                out["hours_to_target"] = round(hrs, 1) if hrs is not None else None
                rng = hours_to_target_range(series, need)
                out["hours_to_target_range"] = [round(rng[0], 1), round(rng[1], 1)] if rng else None
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
        raw = (await self.repo.raw_detailed(device_id, since, until))[-5000:]
        names = await self._user_names({r["entered_by"] for r in raw if r["entered_by"]})
        return {
            "raw": [
                {
                    "t": r["t"].isoformat(),
                    "v": r["v"],
                    "source": r["source"],
                    "entered_by": str(r["entered_by"]) if r["entered_by"] else None,
                    "entered_by_name": names.get(str(r["entered_by"]), "") if r["entered_by"] else "",
                    "note": r["note"],
                }
                for r in raw
            ],
            "hourly": [{**h, "hour": h["hour"].isoformat()} for h in await self.repo.hourly(device_id, since, until)][
                -5000:
            ],
        }

    async def _user_names(self, ids: set[Any]) -> dict[str, str]:
        if not ids:
            return {}
        try:
            from app.modules.users.models import User

            stmt = select(User).where(User.id.in_([uuid.UUID(str(i)) for i in ids]))
            users = (await self.session.execute(stmt)).scalars()
            return {str(u.id): (getattr(u, "full_name", "") or getattr(u, "email", "") or "") for u in users}
        except Exception:
            logger.debug("reading author lookup skipped", exc_info=True)
            return {}

    async def add_user_readings(
        self, device: SensorDevice, readings: list[ReadingIn], source: str, user_id: uuid.UUID | str | None
    ) -> dict[str, Any]:
        """Readings typed in or imported by a person, with their author, note and an audit row each.

        A time that already holds a reading is skipped and reported, never overwritten.
        """
        by = uuid.UUID(str(user_id)) if user_id else None
        latest: dict[datetime, ReadingIn] = {}
        for r in readings:
            latest[_aware(r.recorded_at)] = r
        taken = {_aware(t) for t in await self.repo.existing_times(device.id, list(latest))}
        fresh = {t: r for t, r in latest.items() if t not in taken}
        report: dict[str, Any] = {"accepted": 0, "exceedances": 0, "strips_released": 0}
        if fresh:
            report = await self.ingest(
                device,
                [(t, r.value) for t, r in fresh.items()],
                {t: r.frequency_hz for t, r in fresh.items() if r.frequency_hz is not None},
                source=source,
                entered_by=by,
                notes={t: r.note for t, r in fresh.items()},
            )
            self.session.add_all(
                ReadingAudit(
                    device_id=device.id,
                    recorded_at=t,
                    action="create",
                    value_after=r.value,
                    note=r.note,
                    user_id=by,
                )
                for t, r in fresh.items()
            )
            await self.session.flush()
        report["duplicates"] = sorted(t.isoformat() for t in taken)[:100]
        report["skipped"] = len(taken)
        return report

    async def _editable_reading(
        self, device: SensorDevice, recorded_at: datetime, user_id: uuid.UUID | str, is_manager: bool
    ) -> dict[str, Any]:
        row = await self.repo.reading(device.id, _aware(recorded_at))
        if row is None:
            raise LookupError("reading_not_found")
        if row["source"] not in EDITABLE_SOURCES:
            raise ValueError("device_reading_not_editable")
        if not is_manager and str(row["entered_by"] or "") != str(user_id):
            raise PermissionError("reading_not_yours")
        return row

    async def edit_reading(
        self,
        device: SensorDevice,
        recorded_at: datetime,
        value: float,
        note: str,
        user_id: uuid.UUID | str,
        *,
        is_manager: bool = False,
    ) -> dict[str, Any]:
        """Change a hand-entered reading. Its author or a manager only; the change is audited and re-checked."""
        row = await self._editable_reading(device, recorded_at, user_id, is_manager)
        t = _aware(row["t"])
        await self.repo.update_reading(device.id, t, float(value), note)
        self.session.add(
            ReadingAudit(
                device_id=device.id,
                recorded_at=t,
                action="update",
                value_before=row["v"],
                value_after=float(value),
                note=note,
                user_id=uuid.UUID(str(user_id)),
            )
        )
        exceeded = await self._check_limits(device, [(t, float(value))], {})
        await self._refresh_last(device)
        await self.session.flush()
        self._publish_change(device, t, "update")
        return {"recorded_at": t.isoformat(), "value": float(value), "note": note, "exceedances": exceeded}

    async def delete_reading(
        self, device: SensorDevice, recorded_at: datetime, user_id: uuid.UUID | str, *, is_manager: bool = False
    ) -> None:
        """Remove a hand-entered reading. Its author or a manager only; the audit row keeps the value."""
        row = await self._editable_reading(device, recorded_at, user_id, is_manager)
        t = _aware(row["t"])
        await self.repo.delete_reading(device.id, t)
        self.session.add(
            ReadingAudit(
                device_id=device.id,
                recorded_at=t,
                action="delete",
                value_before=row["v"],
                note=row["note"],
                user_id=uuid.UUID(str(user_id)),
            )
        )
        await self._refresh_last(device)
        await self.session.flush()
        self._publish_change(device, t, "delete")

    async def _refresh_last(self, device: SensorDevice) -> None:
        last = (await self.repo.raw(device.id))[-1:]
        device.last_seen_at, device.last_value = (last[0][0], last[0][1]) if last else (device.last_seen_at, None)

    def _publish_change(self, device: SensorDevice, t: datetime, action: str) -> None:
        event_bus.publish_detached(
            EVENT_READING_CHANGED,
            {
                "device_id": str(device.id),
                "project_id": str(device.project_id),
                "recorded_at": t.isoformat(),
                "action": action,
            },
            source_module="site_sensors",
        )

    async def reading_audit(self, device_id: uuid.UUID) -> list[dict[str, Any]]:
        """Who added, changed or deleted the device's hand-entered readings, newest first."""
        rows = await self.repo.audit(device_id)
        names = await self._user_names({r.user_id for r in rows if r.user_id})
        return [
            {
                "id": str(r.id),
                "recorded_at": r.recorded_at.isoformat(),
                "action": r.action,
                "value_before": r.value_before,
                "value_after": r.value_after,
                "note": r.note,
                "user_id": str(r.user_id) if r.user_id else None,
                "user_name": names.get(str(r.user_id), "") if r.user_id else "",
                "at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

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

    async def context(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Country, unit system and the pours whose formwork may be struck now."""
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        country = ((project.country_code or "") if project else "").upper()
        devices = {d.id: d for d in await self.repo.devices(project_id)}
        ready = []
        for s in await self.list_strips(project_id):
            if s.status != "released" or s.struck_at is not None:
                continue
            est = await self.maturity(s.device_id)
            d = devices.get(s.device_id)
            ready.append(
                {
                    "strip_id": str(s.id),
                    "element": s.element,
                    "device_code": d.code if d else "",
                    "strength_mpa": est.get("strength_mpa"),
                    "target_strength_mpa": float(s.target_strength_mpa),
                }
            )
        return {
            "country": country,
            "unit_system": "imperial" if country in IMPERIAL_COUNTRIES else "metric",
            "strike_ready": ready,
            "limit_grading": limit_grading(country),
        }

    async def sparklines(self, project_id: uuid.UUID, now: datetime | None = None) -> dict[str, Any]:
        """Hourly means of the last 24 hours per device, with the limit line where one applies."""
        now = now or datetime.now(UTC)
        out: dict[str, Any] = {}
        for d in await self.repo.devices(project_id):
            since = now - timedelta(hours=24)
            rows = [(_aware(t), v) for t, v in await self.repo.raw(d.id, since=since, until=now)]
            rows += [(_aware(h["hour"]), float(h["avg"])) for h in await self.repo.hourly(d.id, since=since, until=now)]
            limit, _source = (None, "") if d.kind == "concrete_maturity" else await self.limit_of(d, now)
            out[str(d.id)] = {"points": sparkline(rows, now), "limit": limit}
        return out

    async def pour_record(self, strip_id: uuid.UUID) -> dict[str, Any]:
        """Everything a pour record prints: the strike, the strength, the temperature curve, who and why."""
        strip = await self.session.get(FormworkStrip, strip_id)
        if strip is None:
            raise LookupError("strip_not_found")
        device = await self.get_device(strip.device_id)
        mix = await self.session.get(ConcreteMix, device.mix_id) if device.mix_id else None
        est = await self.maturity(device.id, until=strip.struck_at)
        struck_by = ""
        if strip.struck_by:
            try:
                from app.modules.users.models import User

                user = await self.session.get(User, strip.struck_by)
                struck_by = (getattr(user, "full_name", "") or getattr(user, "email", "")) if user else ""
            except Exception:
                logger.debug("struck_by lookup skipped", exc_info=True)
        return {
            "strip_id": str(strip.id),
            "project_id": str(strip.project_id),
            "element": strip.element,
            "device_code": device.code,
            "pour_ref": device.pour_ref,
            "cast_at": device.cast_at.isoformat() if device.cast_at else None,
            "mix_code": mix.code if mix else "",
            "method": est.get("method"),
            "index_unit": est.get("index_unit"),
            "target_strength_mpa": str(strip.target_strength_mpa),
            "struck_at": strip.struck_at.isoformat() if strip.struck_at else None,
            "strength_at_strike_mpa": str(strip.strength_at_strike_mpa)
            if strip.strength_at_strike_mpa is not None
            else None,
            "maturity_at_strike": est.get("maturity_c_h"),
            "struck_by": struck_by,
            "strike_reason": strip.strike_reason or "",
            "series": est.get("series", []),
        }

    async def validation_payload(self, project_id: uuid.UUID) -> dict[str, Any]:
        await self.sweep_offline(project_id)
        devices = {d.id: d for d in await self.repo.devices(project_id)}
        alerts = await self.repo.alerts(project_id, limit=1000)
        strips = await self.list_strips(project_id)
        mixes = await self.list_mixes(project_id)
        counts = await self.repo.calibration_counts([m.id for m in mixes])
        used_mix_ids = {d.mix_id for d in devices.values() if d.mix_id}
        device_rows = []
        pours = []
        for d in devices.values():
            limit, _source = (None, "") if d.kind == "concrete_maturity" else await self.limit_of(d)
            since = datetime.now(UTC) - timedelta(hours=48)
            stats = reading_stats([(_aware(t), v) for t, v in await self.repo.raw(d.id, since=since)])
            device_rows.append(
                {
                    "id": str(d.id),
                    "code": d.code,
                    "kind": d.kind,
                    "active": d.active,
                    "offline": any(a.device_id == d.id and a.kind == "offline" and a.status == "open" for a in alerts),
                    "has_limit": limit is not None or d.lower_limit is not None,
                    "has_mix": d.mix_id is not None,
                    "unit": d.unit,
                    "record_only": bool(d.record_only),
                    "upper": float(d.limit_value) if d.limit_value is not None else None,
                    "lower": float(d.lower_limit) if d.lower_limit is not None else None,
                    "overrides_country": d.kind not in ("custom", "concrete_maturity")
                    and d.limit_value is not None
                    and (await self.country_limit_of(d))[0] is not None,
                    "limit_note": d.limit_note or "",
                    **stats,
                }
            )
            if d.kind == "concrete_maturity" and d.mix_id and d.active:
                est = await self.maturity(d.id)
                pours.append({"id": str(d.id), "code": d.code, "strength_status": est.get("strength_status")})
        return {
            "devices": device_rows,
            "mixes": [
                {"id": str(m.id), "code": m.code, "points": counts.get(m.id, 0), "r2": m.fit_r2}
                for m in mixes
                if m.id in used_mix_ids or m.project_id == project_id
            ],
            "pours": pours,
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
                    "reason": s.strike_reason or "",
                }
                for s in strips
            ],
            "evidence": await evidence_rows(self.session, project_id),
            "bim_links": await bim_link_rows(self.session, project_id),
            # Read by the site_sensor_links rule set (registered on import), also run under "site_sensors".
            "links": (await build_sensor_link_payload(self.session, project_id))["links"],
        }
