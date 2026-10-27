# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views business logic: ownership, sharing and validation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import RuleResult, Severity
from app.modules.list_views.models import ListView
from app.modules.list_views.repository import ListViewRepository
from app.modules.list_views.schemas import ListViewCreate, ListViewUpdate
from app.modules.list_views.validators import check_view


class ListViewError(Exception):
    """A rejected request; ``status`` is the HTTP status the router returns."""

    def __init__(self, status: int, message: str, findings: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.findings = findings or []


def _finding(r: RuleResult) -> dict[str, Any]:
    return {"rule_id": r.rule_id, "severity": r.severity.value, "message": r.message, "suggestion": r.suggestion}


class ListViewService:
    """List-view operations for one caller (user + tenant)."""

    def __init__(self, session: AsyncSession, *, user_id: uuid.UUID, tenant_id: str) -> None:
        self.repo = ListViewRepository(session)
        self.user_id = user_id
        self.tenant_id = tenant_id

    async def _validate(self, view: ListView) -> list[dict[str, Any]]:
        failing = await check_view(
            {"name": view.name, "scope_key": view.scope_key, "state": view.state, "is_shared": view.is_shared}
        )
        errors = [r for r in failing if r.severity == Severity.ERROR]
        if errors:
            raise ListViewError(422, errors[0].message, [_finding(r) for r in failing])
        return [_finding(r) for r in failing]

    async def list(self, scope_key: str) -> list[ListView]:
        """Own and team-shared views of one page."""
        return await self.repo.list_visible(tenant_id=self.tenant_id, user_id=self.user_id, scope_key=scope_key)

    async def create(self, data: ListViewCreate) -> tuple[ListView, list[dict[str, Any]]]:
        """Save a new view; returns it with its warnings."""
        if await self.repo.find_by_name(user_id=self.user_id, scope_key=data.scope_key, name=data.name):
            raise ListViewError(409, f"A view named {data.name!r} already exists on this list")
        view = ListView(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            scope_key=data.scope_key,
            name=data.name,
            state=data.state.model_dump(),
            is_shared=data.is_shared,
            is_default=data.is_default,
        )
        findings = await self._validate(view)
        if data.is_default:
            await self.repo.clear_default(user_id=self.user_id, scope_key=data.scope_key)
        return await self.repo.add(view), findings

    async def _own(self, view_id: uuid.UUID) -> ListView:
        view = await self.repo.get_visible(view_id, tenant_id=self.tenant_id, user_id=self.user_id)
        if view is None:
            raise ListViewError(404, "View not found")
        if view.user_id != self.user_id:
            raise ListViewError(403, "Only the owner can change a shared view")
        return view

    async def update(self, view_id: uuid.UUID, data: ListViewUpdate) -> tuple[ListView, list[dict[str, Any]]]:
        """Rename, re-share, mark default or overwrite the layout of an own view."""
        view = await self._own(view_id)
        if data.name is not None and data.name.strip() != view.name:
            name = data.name.strip()
            if await self.repo.find_by_name(user_id=self.user_id, scope_key=view.scope_key, name=name):
                raise ListViewError(409, f"A view named {name!r} already exists on this list")
            view.name = name
        if data.state is not None:
            view.state = data.state.model_dump()
        if data.is_shared is not None:
            view.is_shared = data.is_shared
        findings = await self._validate(view)
        if data.is_default is not None:
            if data.is_default:
                await self.repo.clear_default(user_id=self.user_id, scope_key=view.scope_key, keep=view.id)
            view.is_default = data.is_default
        await self.repo.session.flush()
        await self.repo.session.refresh(view)
        return view, findings

    async def delete(self, view_id: uuid.UUID) -> None:
        """Delete an own view."""
        await self.repo.delete(await self._own(view_id))
