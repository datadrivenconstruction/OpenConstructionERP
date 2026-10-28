# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ data access: devices, alerts, and the compact reading tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_sensors.models import (
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

    async def devices_page(
        self, project_id: uuid.UUID, kind: str | None, offset: int, limit: int
    ) -> tuple[list[SensorDevice], int]:
        base = select(SensorDevice).where(SensorDevice.project_id == project_id)
        if kind:
            base = base.where(SensorDevice.kind == kind)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        page = base.order_by(SensorDevice.code, SensorDevice.id).offset(offset).limit(limit)
        return list((await self.session.execute(page)).scalars()), total

    async def device_by_token_hash(self, token_hash: str) -> SensorDevice | None:
        stmt = select(SensorDevice).where(SensorDevice.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def insert_readings(self, device_id: uuid.UUID, rows: list[tuple[datetime, float]]) -> None:
        if not rows:
            return
        stmt = pg_insert(sensor_reading).values(
            [{"device_id": device_id, "recorded_at": t, "value": v} for t, v in rows]
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
        """Aggregate raw rows older than ``before`` into hourly rows, then delete them. Returns rows folded."""
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
            .where(r.c.recorded_at < before)
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
            await self.session.execute(select(func.count()).select_from(r).where(r.c.recorded_at < before))
        ).scalar_one()
        if not count:
            return 0
        await self.session.execute(ins)
        await self.session.execute(delete(r).where(r.c.recorded_at < before))
        return int(count)

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

    async def alerts_page(
        self, project_id: uuid.UUID, status: str | None, offset: int, limit: int
    ) -> tuple[list[SensorAlert], int]:
        base = select(SensorAlert).where(SensorAlert.project_id == project_id)
        if status:
            base = base.where(SensorAlert.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        page = base.order_by(SensorAlert.raised_at.desc(), SensorAlert.id).offset(offset).limit(limit)
        return list((await self.session.execute(page)).scalars()), total

    async def alerts(
        self, project_id: uuid.UUID | None = None, status: str | None = None, limit: int = 200
    ) -> list[SensorAlert]:
        stmt = select(SensorAlert).order_by(SensorAlert.raised_at.desc()).limit(limit)
        if project_id is not None:
            stmt = stmt.where(SensorAlert.project_id == project_id)
        if status:
            stmt = stmt.where(SensorAlert.status == status)
        return list((await self.session.execute(stmt)).scalars())
