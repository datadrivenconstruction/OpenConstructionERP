# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the MCP module: settings rows, MCP tokens and the call log."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog
from app.modules.mcp.models import McpSettings
from app.modules.users.models import APIKey

MCP_AUDIT_MODULE = "mcp"
MCP_AUDIT_ENTITY = "mcp_tool_call"


class McpSettingsRepository:
    """Read and upsert the per-user settings row."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> McpSettings | None:
        """The caller's row, or None when they never touched the settings."""
        stmt = select(McpSettings).where(McpSettings.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_create(self, user_id: uuid.UUID) -> McpSettings:
        """The caller's row, created disabled on first use."""
        row = await self.get(user_id)
        if row is None:
            row = McpSettings(user_id=user_id)
            self.session.add(row)
            await self.session.flush()
        return row


def is_mcp_key(key: APIKey, scope: str) -> bool:
    """Whether an API key row was issued for MCP (declares ``scope``)."""
    return scope in list(key.permissions or [])


class McpTokenRepository:
    """MCP tokens are API keys that declare the MCP access scope."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: uuid.UUID, scope: str) -> list[APIKey]:
        """The caller's MCP tokens, newest first, revoked ones included."""
        stmt = select(APIKey).where(APIKey.user_id == user_id).order_by(APIKey.created_at.desc())
        rows = (await self.session.execute(stmt)).scalars().all()
        return [k for k in rows if is_mcp_key(k, scope)]


class McpCallLogRepository:
    """Reads the tool-call rows the endpoint writes to ``oe_activity_log``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        """How many tool calls the caller has on record."""
        stmt = select(func.count(ActivityLog.id)).where(
            ActivityLog.module == MCP_AUDIT_MODULE,
            ActivityLog.entity_type == MCP_AUDIT_ENTITY,
            ActivityLog.actor_id == user_id,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def recent_for_user(self, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[ActivityLog]:
        """The caller's latest tool calls, newest first."""
        stmt = (
            select(ActivityLog)
            .where(
                ActivityLog.module == MCP_AUDIT_MODULE,
                ActivityLog.entity_type == MCP_AUDIT_ENTITY,
                ActivityLog.actor_id == user_id,
            )
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        """How many tool calls the caller has on record."""
        stmt = select(func.count(ActivityLog.id)).where(
            ActivityLog.module == MCP_AUDIT_MODULE,
            ActivityLog.entity_type == MCP_AUDIT_ENTITY,
            ActivityLog.actor_id == user_id,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_outcome_since(self, user_id: uuid.UUID, outcome: str, since: datetime) -> int:
        """How many of the caller's calls ended with ``outcome`` since ``since``."""
        stmt = select(func.count(ActivityLog.id)).where(
            ActivityLog.module == MCP_AUDIT_MODULE,
            ActivityLog.entity_type == MCP_AUDIT_ENTITY,
            ActivityLog.actor_id == user_id,
            ActivityLog.to_status == outcome,
            ActivityLog.created_at >= since,
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)
