# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for staffing. Every child lookup is by ``(project_id, id)``, so a foreign id is simply absent."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staffing.models import (
    HandoverLink,
    LeaveRecord,
    PersonnelDocument,
    PersonnelFile,
    PositionFill,
    StaffingPlan,
    StaffingPosition,
    TravelRecord,
)


class StaffingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: Any) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def plan(self, project_id: uuid.UUID, *, lock: bool = False) -> StaffingPlan | None:
        stmt = select(StaffingPlan).where(StaffingPlan.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def plans_for_document(self, document_id: uuid.UUID) -> list[StaffingPlan]:
        stmt = select(StaffingPlan).where(StaffingPlan.governance_document_id == document_id).with_for_update()
        return list((await self.session.execute(stmt)).scalars())

    async def child(self, model: type, project_id: uuid.UUID, row_id: uuid.UUID, *, lock: bool = False) -> Any:
        stmt = select(model).where(model.project_id == project_id, model.id == row_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _list(self, model: type, project_id: uuid.UUID, *order: Any, **where: Any) -> list[Any]:
        stmt = select(model).where(model.project_id == project_id)
        for col, value in where.items():
            stmt = stmt.where(getattr(model, col) == value)
        return list((await self.session.execute(stmt.order_by(*order))).scalars())

    async def positions(self, project_id: uuid.UUID) -> list[StaffingPosition]:
        return await self._list(
            StaffingPosition, project_id, StaffingPosition.sort_order, StaffingPosition.entry_date, StaffingPosition.id
        )

    async def fills(self, project_id: uuid.UUID, **where: Any) -> list[PositionFill]:
        return await self._list(PositionFill, project_id, PositionFill.from_date, PositionFill.id, **where)

    async def handovers(self, project_id: uuid.UUID) -> list[HandoverLink]:
        return await self._list(HandoverLink, project_id, HandoverLink.created_at)

    async def files(self, project_id: uuid.UUID) -> list[PersonnelFile]:
        return await self._list(PersonnelFile, project_id, PersonnelFile.created_at)

    async def file_for_member(self, project_id: uuid.UUID, roster_member_id: uuid.UUID) -> PersonnelFile | None:
        stmt = select(PersonnelFile).where(
            PersonnelFile.project_id == project_id, PersonnelFile.roster_member_id == roster_member_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def documents(self, project_id: uuid.UUID, file_id: uuid.UUID | None = None) -> list[PersonnelDocument]:
        where = {"personnel_file_id": file_id} if file_id else {}
        return await self._list(PersonnelDocument, project_id, PersonnelDocument.document_kind, **where)

    async def travels(self, project_id: uuid.UUID, file_id: uuid.UUID | None = None) -> list[TravelRecord]:
        where = {"personnel_file_id": file_id} if file_id else {}
        return await self._list(TravelRecord, project_id, TravelRecord.depart_date, **where)

    async def leaves(self, project_id: uuid.UUID, file_id: uuid.UUID | None = None) -> list[LeaveRecord]:
        where = {"personnel_file_id": file_id} if file_id else {}
        return await self._list(LeaveRecord, project_id, LeaveRecord.from_date, **where)

    async def documents_for_credential(self, credential_id: uuid.UUID) -> list[PersonnelDocument]:
        stmt = select(PersonnelDocument).where(PersonnelDocument.credential_id == credential_id)
        return list((await self.session.execute(stmt)).scalars())

    async def file_ids_due(self, today: Any) -> list[uuid.UUID]:
        """Ended files whose stored retention date has passed. A held file is not ``ended`` and is not listed."""
        stmt = (
            select(PersonnelFile.id)
            .where(
                PersonnelFile.status == "ended",
                PersonnelFile.retention_due_at.is_not(None),
                PersonnelFile.retention_due_at <= today,
            )
            .order_by(PersonnelFile.retention_due_at, PersonnelFile.id)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def file_for_retention(self, file_id: uuid.UUID) -> PersonnelFile | None:
        """One file under a row lock; ``None`` when another worker holds it or it is gone."""
        stmt = select(PersonnelFile).where(PersonnelFile.id == file_id).with_for_update(skip_locked=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()
