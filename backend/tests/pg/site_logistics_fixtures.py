# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the site-logistics plan PostgreSQL tests.

A world is a throwaway database with real users and a project whose team holds
a manager and an editor; an outsider is a manager of nothing here. The plan is
started on the shipped ``neutral`` catalogue by its first write, which sets the
site time zone. That zone is not UTC on purpose: every window a test builds is
a site clock time, PostgreSQL hands it back as an instant, and a rule that read
the UTC clock would be five and a half hours off. Everything commits for real.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.site_logistics.plan_service import LogisticsPlanService
from tests.pg.governance_fixtures import add_project, add_user

BASE = "/api/v1/site-logistics"
SQUARE_M2 = "10000"
SITE_ZONE = "Asia/Kolkata"
SITE = ZoneInfo(SITE_ZONE)


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    editor: uuid.UUID
    outsider: uuid.UUID


async def build_world(
    factory: async_sessionmaker[AsyncSession], *, start_plan: bool = True, site_zone: str | None = SITE_ZONE
) -> World:
    async with factory() as s:
        manager = await add_user(s, "manager")
        editor = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [editor])
        if start_plan:
            # The first write starts the plan (concept and initial stage); a read never does.
            await LogisticsPlanService(s).put_concept(pid, {"site_timezone": site_zone}, manager)
        await s.commit()
    return World(factory, pid, manager, editor, outsider)


def square(side: float, x: float = 0, y: float = 0) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[x, y], [x + side, y], [x + side, y + side], [x, y + side], [x, y]]],
    }


def window(days: int, hour: int, hours: int) -> tuple[datetime, datetime]:
    """A window ``days`` from now at ``hour`` on the site clock, ``hours`` long."""
    base = (datetime.now(SITE) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return base, base + timedelta(hours=hours)


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.site_logistics.router import router

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user_id), "role": role, "permissions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://logistics-test") as c:
        yield c
