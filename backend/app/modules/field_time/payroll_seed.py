# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payroll hours export demo: two sample profiles, payroll references and a few overtime lines.

The pay codes (1000, 1200, REG) are sample values marked ``is_sample``; a customer's codes
belong to their own payroll system. Workers come from the already seeded field-time register:
the first two get a payroll reference and one worker is left without one, so the export card
shows its "no payroll reference" issue on first open. Idempotent.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
from app.modules.field_time.payroll_models import PayrollExportProfile
from app.modules.resources.models import Resource

logger = logging.getLogger(__name__)

_DE = {
    "columns": [
        {"header": "Personalnummer", "source": "worker_ref"},
        {"header": "Datum", "source": "date"},
        {"header": "Projekt", "source": "project_code"},
        {"header": "Kostenstelle", "source": "cost_code"},
        {"header": "Lohnart", "source": "pay_code"},
        {"header": "Stunden", "source": "hours"},
    ],
    "delimiter": ";",
    "decimal": ",",
    "date_format": "DD.MM.YYYY",
    "encoding": "utf-8",
    "grouping": "day",
    "pay_codes": {"regular": "1000", "overtime": "1200"},
}
_US = {
    "columns": [
        {"header": "Employee ID", "source": "worker_ref"},
        {"header": "Week ending", "source": "date"},
        {"header": "Job", "source": "project_code"},
        {"header": "Cost code", "source": "cost_code"},
        {"header": "Pay code", "source": "pay_code"},
        {"header": "Hours", "source": "hours"},
    ],
    "delimiter": ",",
    "decimal": ".",
    "date_format": "MM/DD/YYYY",
    "encoding": "utf-8",
    "grouping": "week",
    "week_start": 0,
    "pay_codes": {"regular": "REG", "overtime": "OT"},
}
_REFS = ("1047", "2210")


async def seed_payroll_export_demo(session: AsyncSession, project_ids: list[uuid.UUID] | None = None) -> dict[str, int]:
    created = 0
    for name, config in (("Payroll DE", _DE), ("Payroll US", _US)):
        exists = (
            await session.execute(select(PayrollExportProfile).where(PayrollExportProfile.name == name))
        ).scalar_one_or_none()
        if exists is None:
            session.add(PayrollExportProfile(name=name, is_sample=True, config=config))
            created += 1
    await session.flush()

    stmt = (
        select(Resource)
        .join(FieldTimesheetLine, FieldTimesheetLine.resource_id == Resource.id)
        .where(Resource.resource_type == "person")
        .order_by(Resource.code)
        .distinct()
    )
    workers = list((await session.execute(stmt)).scalars().all())
    referenced = 0
    for worker, ref in zip(workers, _REFS, strict=False):
        if not worker.payroll_ref:
            worker.payroll_ref = ref
            referenced += 1

    marked = 0
    if len(workers) > 1:
        line = (
            await session.execute(
                select(FieldTimesheetLine)
                .join(FieldTimesheet, FieldTimesheet.id == FieldTimesheetLine.timesheet_id)
                .where(
                    FieldTimesheetLine.resource_id == workers[0].id,
                    FieldTimesheet.status == "approved",
                    FieldTimesheetLine.hour_type == "regular",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if line is not None and line.hours > 8:
            line.hour_type = "overtime"
            marked = 1
    await session.flush()
    return {"profiles": created, "payroll_refs": referenced, "overtime_lines": marked}
