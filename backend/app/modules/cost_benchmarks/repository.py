# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks data access. Every read is bound to one tenant."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cost_benchmarks.models import BenchmarkRecord


async def records_for_tenant(session: AsyncSession, tenant_id: str, kind: str | None = None) -> list[BenchmarkRecord]:
    """The tenant's records, newest cost date first; an empty tenant reads nothing."""
    if not tenant_id:
        return []
    stmt = select(BenchmarkRecord).where(BenchmarkRecord.tenant_id == tenant_id)
    if kind:
        stmt = stmt.where(BenchmarkRecord.kind == kind)
    return list((await session.execute(stmt.order_by(BenchmarkRecord.cost_date.desc()))).scalars().all())
