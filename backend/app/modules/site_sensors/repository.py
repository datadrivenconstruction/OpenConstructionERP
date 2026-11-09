# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ data access: devices, alerts, and the compact reading tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_sensors.models import (
    CalibrationPoint,
    ReadingAudit,
    SensorAlert,
    SensorDevice,
    sensor_reading,
    sensor_reading_hourly,
)


class SiteSensorsRepository:
    """Queries the service needs; no business rules here."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def devices(self, project_id: uuid.UUID | None = None, kind: str | None = None) -> list[SensorDevice]:
        stmt = select(SensorDevice).order_by(SensorDevice.code)
        if project_id is not None:
            stmt = stmt.where(SensorDevice.project_id == project_id)
        if kind:
            stmt = stmt.where(SensorDevice.kind == kind)
        return list((await self.session.execute(stmt)).scalars())

    async def device_by_token_hash(self, token_hash: str) -> SensorDevice | None:
        stmt = select(SensorDevice).where(SensorDevice.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def insert_readings(
        self,
        device_id: uuid.UUID,
        rows: list[tuple[datetime, float]],
        frequencies: dict[datetime, float] | None = None,
        *,
        source: str = "device",
        entered_by: uuid.UUID | None = None,
        notes: dict[datetime, str] | None = None,
    ) -> None:
        if not rows:
            return
        freq = frequencies or {}
        notes = notes or {}
        stmt = pg_insert(sensor_reading).values(
            [
                {
                    "device_id": device_id,
                    "recorded_at": t,
                    "value": v,
                    "frequency_hz": freq.get(t),
                    "source": source,
                    "entered_by": entered_by,
                    "note": notes.get(t, ""),
                }
                for t, v in rows
            ]
        )
        await self.session.execute(stmt.on_conflict_do_nothing(index_elements=["device_id", "recorded_at"]))

    async def raw(
        self, device_id: uuid.UUID, since: datetime | None = None, until: datetime | None = None
    ) -> list[tuple[datetime, float]]:
        stmt = select(sensor_reading.c.recorded_at, sensor_reading.c.value).where(
            sensor_reading.c.device_id == device_id
        )
        if since is not None:
            stmt = stmt.where(sensor_reading.c.recorded_at >= since)
        if until is not None:
            stmt = stmt.where(sensor_reading.c.recorded_at <= until)
        return [(r[0], r[1]) for r in (await self.session.execute(stmt.order_by(sensor_reading.c.recorded_at))).all()]

    async def existing_times(self, device_id: uuid.UUID, times: list[datetime]) -> set[datetime]:
        """Which of these times already hold a reading on the device."""
        if not times:
            return set()
        r = sensor_reading
        stmt = select(r.c.recorded_at).where(r.c.device_id == device_id, r.c.recorded_at.in_(times))
        return set((await self.session.execute(stmt)).scalars())

    async def raw_detailed(
        self, device_id: uuid.UUID, since: datetime | None = None, until: datetime | None = None
    ) -> list[dict[str, Any]]:
        r = sensor_reading
        stmt = select(r.c.recorded_at, r.c.value, r.c.source, r.c.entered_by, r.c.note).where(
            r.c.device_id == device_id
        )
        if since is not None:
            stmt = stmt.where(r.c.recorded_at >= since)
        if until is not None:
            stmt = stmt.where(r.c.recorded_at <= until)
        rows = (await self.session.execute(stmt.order_by(r.c.recorded_at))).all()
        return [
            {"t": x[0], "v": x[1], "source": x[2] or "device", "entered_by": x[3], "note": x[4] or ""} for x in rows
        ]

    async def reading(self, device_id: uuid.UUID, recorded_at: datetime) -> dict[str, Any] | None:
        r = sensor_reading
        stmt = select(r.c.recorded_at, r.c.value, r.c.source, r.c.entered_by, r.c.note).where(
            r.c.device_id == device_id, r.c.recorded_at == recorded_at
        )
        x = (await self.session.execute(stmt)).first()
        if x is None:
            return None
        return {"t": x[0], "v": x[1], "source": x[2] or "device", "entered_by": x[3], "note": x[4] or ""}

    async def update_reading(self, device_id: uuid.UUID, recorded_at: datetime, value: float, note: str) -> None:
        r = sensor_reading
        await self.session.execute(
            update(r).where(r.c.device_id == device_id, r.c.recorded_at == recorded_at).values(value=value, note=note)
        )

    async def delete_reading(self, device_id: uuid.UUID, recorded_at: datetime) -> None:
        r = sensor_reading
        await self.session.execute(delete(r).where(r.c.device_id == device_id, r.c.recorded_at == recorded_at))

    async def audit(self, device_id: uuid.UUID, limit: int = 200) -> list[ReadingAudit]:
        stmt = (
            select(ReadingAudit)
            .where(ReadingAudit.device_id == device_id)
            .order_by(ReadingAudit.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def hourly(
        self, device_id: uuid.UUID, since: datetime | None = None, until: datetime | None = None
    ) -> list[dict[str, Any]]:
        t = sensor_reading_hourly
        stmt = select(t.c.hour, t.c.n, t.c.v_min, t.c.v_max, t.c.v_avg).where(t.c.device_id == device_id)
        if since is not None:
            stmt = stmt.where(t.c.hour >= since)
        if until is not None:
            stmt = stmt.where(t.c.hour <= until)
        rows = (await self.session.execute(stmt.order_by(t.c.hour))).all()
        return [{"hour": r[0], "n": r[1], "min": r[2], "max": r[3], "avg": r[4]} for r in rows]

    async def fold_into_hourly(self, before: datetime) -> int:
        """Aggregate raw device rows older than ``before`` into hourly rows, then delete them. Returns rows folded.

        Readings a person entered stay raw: they carry a note and an author, and the audit trail points at them.
        """
        r = sensor_reading
        hour = func.date_trunc("hour", r.c.recorded_at)
        agg = (
            select(
                r.c.device_id,
                hour.label("hour"),
                func.count().label("n"),
                func.min(r.c.value).label("v_min"),
                func.max(r.c.value).label("v_max"),
                func.avg(r.c.value).label("v_avg"),
            )
            .where(r.c.recorded_at < before, r.c.source == "device")
            .group_by(r.c.device_id, hour)
        )
        h = sensor_reading_hourly
        ins = pg_insert(h).from_select(["device_id", "hour", "n", "v_min", "v_max", "v_avg"], agg)
        # A second fold of the same hour (late readings) merges into the row already there.
        total_n = h.c.n + ins.excluded.n
        ins = ins.on_conflict_do_update(
            index_elements=["device_id", "hour"],
            set_={
                "n": total_n,
                "v_min": func.least(h.c.v_min, ins.excluded.v_min),
                "v_max": func.greatest(h.c.v_max, ins.excluded.v_max),
                "v_avg": (h.c.v_avg * h.c.n + ins.excluded.v_avg * ins.excluded.n) / total_n,
            },
        )
        count = (
            await self.session.execute(
                select(func.count()).select_from(r).where(r.c.recorded_at < before, r.c.source == "device")
            )
        ).scalar_one()
        if not count:
            return 0
        await self.session.execute(ins)
        await self.session.execute(delete(r).where(r.c.recorded_at < before, r.c.source == "device"))
        return int(count)

    async def calibration(self, mix_id: uuid.UUID) -> list[CalibrationPoint]:
        stmt = (
            select(CalibrationPoint).where(CalibrationPoint.mix_id == mix_id).order_by(CalibrationPoint.maturity_index)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def calibration_counts(self, mix_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not mix_ids:
            return {}
        stmt = (
            select(CalibrationPoint.mix_id, func.count())
            .where(CalibrationPoint.mix_id.in_(mix_ids))
            .group_by(CalibrationPoint.mix_id)
        )
        return {r[0]: int(r[1]) for r in (await self.session.execute(stmt)).all()}

    async def replace_calibration(self, mix_id: uuid.UUID, points: list[CalibrationPoint]) -> None:
        await self.session.execute(delete(CalibrationPoint).where(CalibrationPoint.mix_id == mix_id))
        self.session.add_all(points)
        await self.session.flush()

    async def open_alert(self, device_id: uuid.UUID, kind: str) -> SensorAlert | None:
        stmt = (
            select(SensorAlert)
            .where(SensorAlert.device_id == device_id, SensorAlert.kind == kind, SensorAlert.status == "open")
            .order_by(SensorAlert.raised_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def any_alert(self, device_id: uuid.UUID, kind: str) -> SensorAlert | None:
        stmt = select(SensorAlert).where(SensorAlert.device_id == device_id, SensorAlert.kind == kind).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def alerts(
        self, project_id: uuid.UUID | None = None, status: str | None = None, limit: int = 200
    ) -> list[SensorAlert]:
        stmt = select(SensorAlert).order_by(SensorAlert.raised_at.desc()).limit(limit)
        if project_id is not None:
            stmt = stmt.where(SensorAlert.project_id == project_id)
        if status:
            stmt = stmt.where(SensorAlert.status == status)
        return list((await self.session.execute(stmt)).scalars())
