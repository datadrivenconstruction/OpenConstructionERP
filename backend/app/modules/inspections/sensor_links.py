# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Formwork strike release inspections from site sensors.

Striking a strip opens a ``formwork_strike_release`` inspection whose
checklist is prefilled with what the sensor knows: strength at strike against
the target, concrete age, and the lowest concrete temperature since the pour.
The inspector confirms each line; nothing is passed automatically. The
inspection is linked from the device's strength-reached alert.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inspections.models import QualityInspection
from app.modules.inspections.repository import InspectionRepository

logger = logging.getLogger(__name__)

INSPECTION_TYPE = "formwork_strike_release"


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _existing(session: AsyncSession, project_id: uuid.UUID, strip_id: str) -> QualityInspection | None:
    stmt = select(QualityInspection).where(
        QualityInspection.project_id == project_id, QualityInspection.inspection_type == INSPECTION_TYPE
    )
    for row in (await session.execute(stmt)).scalars():
        if (row.metadata_ or {}).get("strip_id") == strip_id:
            return row
    return None


def build_checklist(
    *, strength: float | None, target: float, age_hours: float | None, min_temp_c: float | None
) -> list[dict[str, Any]]:
    """The three release checks, with the sensor's reading as a note and no response yet."""

    def line(key: str, question: str, note: str) -> dict[str, Any]:
        return {
            "id": key,
            "category": "formwork_strike",
            "question": question,
            "question_key": f"inspections.strike_release.{key}",
            "response_type": "yes_no",
            "response": None,
            "notes": note,
            "critical": True,
        }

    return [
        line(
            "strength",
            "Strength at strike reached the target",
            f"{strength:g} MPa / {target:g} MPa" if strength is not None else f"- / {target:g} MPa",
        ),
        line("age", "Concrete age is enough for the element", f"{age_hours:.0f} h" if age_hours is not None else "-"),
        line(
            "temperature",
            "Concrete stayed above the curing minimum",
            f"min {min_temp_c:g} degC" if min_temp_c is not None else "-",
        ),
    ]


async def create_strike_inspection(session: AsyncSession, data: dict[str, Any]) -> QualityInspection | None:
    """Open the release inspection for a struck strip. Idempotent per strip."""
    from app.modules.site_sensors.models import FormworkStrip, SensorAlert, sensor_reading, sensor_reading_hourly

    strip_id, project_id = _uuid(data.get("strip_id")), _uuid(data.get("project_id"))
    if strip_id is None or project_id is None:
        return None
    strip = await session.get(FormworkStrip, strip_id)
    if strip is None or strip.project_id != project_id:
        return None
    found = await _existing(session, project_id, str(strip_id))
    if found is not None:
        return found
    struck = _aware(strip.struck_at or datetime.now(UTC))
    first_raw, min_raw = (
        await session.execute(
            select(func.min(sensor_reading.c.recorded_at), func.min(sensor_reading.c.value)).where(
                sensor_reading.c.device_id == strip.device_id, sensor_reading.c.recorded_at <= struck
            )
        )
    ).one()
    first_hr, min_hr = (
        await session.execute(
            select(func.min(sensor_reading_hourly.c.hour), func.min(sensor_reading_hourly.c.v_min)).where(
                sensor_reading_hourly.c.device_id == strip.device_id, sensor_reading_hourly.c.hour <= struck
            )
        )
    ).one()
    firsts = [_aware(t) for t in (first_raw, first_hr) if t is not None]
    mins = [v for v in (min_raw, min_hr) if v is not None]
    age = (struck - min(firsts)).total_seconds() / 3600 if firsts else None
    strength = float(strip.strength_at_strike_mpa) if strip.strength_at_strike_mpa is not None else None
    inspection = QualityInspection(
        project_id=project_id,
        inspection_number="",
        inspection_type=INSPECTION_TYPE,
        title=f"Formwork strike release: {strip.element}"[:500],
        location=strip.element or None,
        inspection_date=struck.date().isoformat(),
        status="scheduled",
        checklist_data=build_checklist(
            strength=strength,
            target=float(strip.target_strength_mpa),
            age_hours=age,
            min_temp_c=min(mins) if mins else None,
        ),
        metadata_={
            "source_module": "site_sensors",
            "strip_id": str(strip_id),
            "device_id": str(strip.device_id),
            "title_key": "inspections.strike_release.title",
        },
    )
    inspection = await InspectionRepository(session).create(inspection)
    alert = (
        (
            await session.execute(
                select(SensorAlert).where(
                    SensorAlert.device_id == strip.device_id,
                    SensorAlert.kind == "strength_reached",
                    SensorAlert.inspection_id.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )
    if alert is not None:
        alert.inspection_id = inspection.id
    await session.flush()
    return inspection
