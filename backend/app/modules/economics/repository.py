# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for economics. Every child lookup is by ``(project_id, id)``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.economics.models import (
    Approval,
    EconomicsPlan,
    FlowLine,
    FrameLine,
    FundingSource,
    Insurance,
    ProcessSetup,
    Security,
    TaxTreatment,
    Tranche,
)


class EconomicsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def plan(self, project_id: uuid.UUID, *, lock: bool = False) -> EconomicsPlan | None:
        stmt = select(EconomicsPlan).where(EconomicsPlan.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _child(self, model: type, project_id: uuid.UUID, row_id: uuid.UUID) -> Any:
        stmt = select(model).where(model.project_id == project_id, model.id == row_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _list(self, model: type, project_id: uuid.UUID, *order: Any) -> list[Any]:
        stmt = select(model).where(model.project_id == project_id).order_by(*order)
        return list((await self.session.execute(stmt)).scalars())

    async def flow_line(self, project_id: uuid.UUID, line_id: uuid.UUID) -> FlowLine | None:
        return await self._child(FlowLine, project_id, line_id)

    async def flow_lines(self, project_id: uuid.UUID) -> list[FlowLine]:
        return await self._list(FlowLine, project_id, FlowLine.sort_order, FlowLine.created_at)

    async def frame_line(self, project_id: uuid.UUID, line_id: uuid.UUID) -> FrameLine | None:
        return await self._child(FrameLine, project_id, line_id)

    async def frame_lines(self, project_id: uuid.UUID) -> list[FrameLine]:
        return await self._list(FrameLine, project_id, FrameLine.sort_order, FrameLine.code)

    async def source(self, project_id: uuid.UUID, source_id: uuid.UUID) -> FundingSource | None:
        return await self._child(FundingSource, project_id, source_id)

    async def sources(self, project_id: uuid.UUID) -> list[FundingSource]:
        return await self._list(FundingSource, project_id, FundingSource.sort_order, FundingSource.created_at)

    async def tranche(self, project_id: uuid.UUID, tranche_id: uuid.UUID) -> Tranche | None:
        return await self._child(Tranche, project_id, tranche_id)

    async def tranches(self, project_id: uuid.UUID) -> list[Tranche]:
        return await self._list(Tranche, project_id, Tranche.due_on, Tranche.created_at)

    async def approval(self, project_id: uuid.UUID, approval_id: uuid.UUID) -> Approval | None:
        return await self._child(Approval, project_id, approval_id)

    async def approvals(self, project_id: uuid.UUID) -> list[Approval]:
        stmt = select(Approval).where(Approval.project_id == project_id).order_by(Approval.number.desc())
        return list((await self.session.execute(stmt)).scalars())

    async def next_approval_number(self, project_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(Approval.number), 0)).where(Approval.project_id == project_id)
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def next_sort(self, model: type, project_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(model.sort_order), 0)).where(model.project_id == project_id)
        return int((await self.session.execute(stmt)).scalar_one()) + 10

    async def securities(self, project_id: uuid.UUID) -> list[Security]:
        return await self._list(Security, project_id, Security.sort_order, Security.created_at)

    async def security(self, project_id: uuid.UUID, row_id: uuid.UUID) -> Security | None:
        return await self._child(Security, project_id, row_id)

    async def insurances(self, project_id: uuid.UUID) -> list[Insurance]:
        return await self._list(Insurance, project_id, Insurance.sort_order, Insurance.created_at)

    async def insurance(self, project_id: uuid.UUID, row_id: uuid.UUID) -> Insurance | None:
        return await self._child(Insurance, project_id, row_id)

    async def tax(self, project_id: uuid.UUID) -> TaxTreatment | None:
        stmt = select(TaxTreatment).where(TaxTreatment.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def processes(self, project_id: uuid.UUID) -> list[ProcessSetup]:
        return await self._list(ProcessSetup, project_id, ProcessSetup.area)
