# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data-access layer for compliance DSL rules."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.models import ComplianceDSLRule


class ComplianceDSLRepository:
    """Persistence surface for :class:`ComplianceDSLRule` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads ------------------------------------------------------------

    async def get_by_pk(
        self,
        rule_pk: uuid.UUID | str,
        *,
        tenant_id: str | None,
    ) -> ComplianceDSLRule | None:
        stmt = select(ComplianceDSLRule).where(
            ComplianceDSLRule.id == _as_uuid(rule_pk)
        )
        if tenant_id is not None:
            stmt = stmt.where(ComplianceDSLRule.tenant_id == str(tenant_id))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_rule_id(
        self,
        rule_id: str,
        *,
        tenant_id: str | None,
    ) -> ComplianceDSLRule | None:
        stmt = select(ComplianceDSLRule).where(
            ComplianceDSLRule.rule_id == rule_id
        )
        if tenant_id is not None:
            stmt = stmt.where(ComplianceDSLRule.tenant_id == str(tenant_id))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_tenant(
        self,
        *,
        tenant_id: str | None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ComplianceDSLRule], int]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        limit = min(limit, 500)

        base = select(ComplianceDSLRule)
        if tenant_id is not None:
            base = base.where(ComplianceDSLRule.tenant_id == str(tenant_id))
        if active_only:
            base = base.where(ComplianceDSLRule.is_active.is_(True))

        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        rows_stmt = (
            base.order_by(ComplianceDSLRule.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.execute(rows_stmt)).scalars().all()
        return list(rows), int(total)

    async def list_all_active(self) -> list[ComplianceDSLRule]:
        """Used at startup to register every active rule into the registry."""
        stmt = select(ComplianceDSLRule).where(
            ComplianceDSLRule.is_active.is_(True)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # -- writes -----------------------------------------------------------

    async def add(self, row: ComplianceDSLRule) -> ComplianceDSLRule:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: ComplianceDSLRule) -> None:
        await self.session.delete(row)
        await self.session.flush()


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


__all__ = ["ComplianceDSLRepository"]
