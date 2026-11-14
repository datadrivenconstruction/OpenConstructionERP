"""Two demo installs racing (boot seed vs API call) must not collide on shared rows.

The loser used to miss the winner's uncommitted project and fail on the duplicate
contract code, or on the accounting sync connection name, with a 500.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.demo_projects import _lock_demo_installs, install_demo_project
from app.modules.accounting_sync.demo import LIVE_NAME, seed_demo_accounting_sync
from app.modules.accounting_sync.models import AccountingConnection
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine


@pytest.mark.asyncio
async def test_the_install_lock_makes_a_second_session_wait_for_the_first_commit() -> None:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as first, factory() as second:
            await _lock_demo_installs(first)
            waiter = asyncio.create_task(_lock_demo_installs(second))
            await asyncio.sleep(0.5)
            assert not waiter.done()
            await first.commit()
            await asyncio.wait_for(waiter, timeout=10)


@pytest.mark.asyncio
async def test_a_concurrent_second_install_answers_already_installed() -> None:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def install() -> dict:
            async with factory() as session:
                result = await install_demo_project(session, "condo-toronto")
                await session.commit()
                return result

        results = await asyncio.gather(install(), install())
        assert sorted(bool(r.get("already_installed")) for r in results) == [False, True]
        async with factory() as session:
            count = (await session.execute(text("SELECT count(*) FROM oe_projects_project"))).scalar_one()
            assert count == 1


@pytest.mark.asyncio
async def test_concurrent_accounting_demo_seeds_share_one_connection() -> None:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as setup:
            owner = User(email=f"o-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
            setup.add(owner)
            await setup.flush()
            projects = [Project(name=f"P{i}", owner_id=owner.id, project_code=f"P-{i}") for i in range(2)]
            setup.add_all(projects)
            await setup.commit()
            ids = [p.id for p in projects]

        async def seed(project_id: uuid.UUID) -> None:
            async with factory() as session:
                await seed_demo_accounting_sync(session, project_id=project_id, currency="EUR")
                await asyncio.sleep(0.3)
                await session.commit()

        await asyncio.gather(*(seed(i) for i in ids))
        async with factory() as session:
            rows = (
                (await session.execute(select(AccountingConnection).where(AccountingConnection.name == LIVE_NAME)))
                .scalars()
                .all()
            )
            assert len(rows) == 1
