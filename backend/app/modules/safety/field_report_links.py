# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Field report safety text -> an open safety observation for HSE triage.

A site manager writes "worker slipped on scaffold" in the daily field report.
That sentence must reach the safety register, not stay buried in a report. It
becomes one open ``unsafe_condition`` observation linked back to the report;
the HSE officer classifies it (and raises an incident if it was one). An
observation, not an incident, because the text is unclassified.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import SafetyObservation
from app.modules.safety.repository import ObservationRepository

SOURCE_KEY = "field_report_id"


async def record_field_report_safety(session: AsyncSession, data: dict[str, Any]) -> SafetyObservation | None:
    """Create (once) the observation for a submitted report's safety text."""
    from app.modules.fieldreports.models import FieldReport

    try:
        report_id = uuid.UUID(str(data.get("report_id")))
    except (TypeError, ValueError):
        return None
    report = await session.get(FieldReport, report_id)
    if report is None:
        return None
    text = (report.safety_incidents or "").strip()
    if not text:
        return None
    rows = (
        await session.execute(select(SafetyObservation).where(SafetyObservation.project_id == report.project_id))
    ).scalars()
    for row in rows:
        if (row.metadata_ or {}).get(SOURCE_KEY) == str(report_id):
            return row
    observation = SafetyObservation(
        project_id=report.project_id,
        observation_number="",
        observation_type="unsafe_condition",
        description=text,
        severity=2,
        likelihood=3,
        risk_score=6,
        status="open",
        metadata_={
            "source_module": "fieldreports",
            SOURCE_KEY: str(report_id),
            "report_date": str(report.report_date),
            "message_key": "safety.from_field_report",
        },
    )
    return await ObservationRepository(session).create(observation)
