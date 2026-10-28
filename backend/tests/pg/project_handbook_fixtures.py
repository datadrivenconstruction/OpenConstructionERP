# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the project handbook PostgreSQL tests.

A world is a throwaway database with real users and a project, optionally running governance on the
shipped ``elf_module_framework`` model (which carries the 174 folders the data room materialises), and a
handbook pinned to the neutral shipped catalogue. Everything commits for real.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.project_governance.service import GovernanceService
from app.modules.project_handbook.service import Actor, ProjectHandbookService
from tests.pg.governance_fixtures import World, add_project, add_user


async def build_world(
    factory: async_sessionmaker[AsyncSession], *, governance: bool = False, handbook: bool = True
) -> World:
    from app.modules.project_handbook.catalogue import register_kinds

    register_kinds()
    async with factory() as s:
        manager = await add_user(s, "manager")
        decider = await add_user(s, "manager")
        owner = await add_user(s, "manager")
        editor = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [decider, owner, editor])
        w = World(factory, pid, manager, decider, owner, editor, outsider)
        if governance:
            await GovernanceService(s).set_model(
                pid,
                source="shipped",
                catalogue_id="elf_module_framework",
                version=None,
                four_eyes=True,
                actor_id=manager,
                tenant_id=str(manager),
            )
        if handbook:
            await ProjectHandbookService(s).create_handbook(
                pid,
                actor_id=manager,
                tenant_id=str(manager),
                catalogue_id="neutral",
                title="Handbook",
                default_owner_id=owner,
            )
        await s.commit()
    return w


async def call(w: World, fn: str, *args: Any, **kw: Any) -> Any:
    """Run one service method in its own committed session."""
    async with w.factory() as s:
        out = await getattr(ProjectHandbookService(s), fn)(w.project_id, *args, **kw)
        await s.commit()
        return out


def actor(user_id: uuid.UUID, *, edit: bool = True, manage: bool = False) -> Actor:
    return Actor(user_id, manage=manage, edit=edit)


async def add_document(w: World, name: str, category: str = "other") -> uuid.UUID:
    from app.modules.documents.models import Document

    async with w.factory() as s:
        doc = Document(project_id=w.project_id, name=name, category=category, uploaded_by=str(w.manager))
        s.add(doc)
        await s.commit()
        return doc.id
