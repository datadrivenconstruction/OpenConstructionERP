# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submitted field report -> one linked entry in that day's open diary.

Canonical split: the field report owns crew/plant hours, weather and delays
(it feeds cost, payroll and schedule progress); the daily diary is the signed
contemporaneous record. The diary therefore links the report instead of
copying its numbers. A weather or other delay is named in the entry so the
signed record a claim relies on carries it. No diary is created here: a diary
is started by a person.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.daily_diary.models import DailyDiary, DiaryEntry

SOURCE_MODULE = "fieldreports"


async def link_field_report(session: AsyncSession, data: dict[str, Any]) -> DiaryEntry | None:
    """Add (once) the diary entry pointing at a submitted field report."""
    from app.modules.fieldreports.models import FieldReport

    try:
        report_id = uuid.UUID(str(data.get("report_id")))
    except (TypeError, ValueError):
        return None
    report = await session.get(FieldReport, report_id)
    if report is None:
        return None
    day = str(report.report_date)
    diary = (
        (
            await session.execute(
                select(DailyDiary).where(
                    DailyDiary.project_id == report.project_id,
                    DailyDiary.diary_date == day,
                    DailyDiary.status == "open",
                )
            )
        )
        .scalars()
        .first()
    )
    if diary is None:
        return None
    existing = (
        (
            await session.execute(
                select(DiaryEntry).where(
                    DiaryEntry.diary_id == diary.id,
                    DiaryEntry.source_module == SOURCE_MODULE,
                    DiaryEntry.source_ref == report_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    delay_hours = float(report.delay_hours or 0)
    params: dict[str, Any] = {"weather": report.weather_condition, "delay_hours": delay_hours}
    if delay_hours > 0:
        title_key = "daily_diary.field_report.delay"
        title = f"Field report: {delay_hours:g} h delay"
        params["delays"] = report.delays or ""
    else:
        title_key = "daily_diary.field_report.linked"
        title = "Field report submitted"
    entry = DiaryEntry(
        diary_id=diary.id,
        entry_type="event",
        entry_time=datetime.now(UTC),
        title=title[:500],
        description=report.delays if delay_hours > 0 else None,
        source_module=SOURCE_MODULE,
        source_ref=report_id,
        metadata_={"title_key": title_key, "params": params, "delay": delay_hours > 0},
    )
    session.add(entry)
    await session.flush()
    return entry
