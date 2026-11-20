"""A pack's demo projects are installed once, and a test start installs none.

Two consecutive starts with a country pack active must leave the demo project
count where the first start put it, and a start that asks for a fast startup
(every test app start) must not seed the pack's demos at all, the same as the
generic showcase.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database as app_database
from app.modules.projects.models import Project

pytestmark = pytest.mark.asyncio

_PACK = "hungary-hu"


@pytest_asyncio.fixture
async def boot_factory(pg_session, monkeypatch, no_detached_subscribers):
    """Boot sessions joined to the test's outer transaction through savepoints."""
    factory = async_sessionmaker(
        bind=pg_session.bind,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    monkeypatch.setattr(app_database, "async_session_factory", factory)
    return factory


async def _pack_demo_count(factory) -> int:
    async with factory() as s:
        stmt = select(func.count()).select_from(Project).where(Project.metadata_["partner_pack"].as_string() == _PACK)
        return int((await s.execute(stmt)).scalar_one())


async def test_two_boot_installs_of_a_pack_leave_the_count_unchanged(boot_factory) -> None:
    from app.core.demo_projects import install_demo_projects_at_boot
    from app.core.partner_pack.discovery import get_pack_by_slug
    from app.main import _pack_demo_ids

    pack = get_pack_by_slug(_PACK)
    if pack is None:
        pytest.skip(f"{_PACK} is not discoverable in this layout")
    demo_ids = _pack_demo_ids(pack)
    assert demo_ids, "the pack pins demo projects"

    await install_demo_projects_at_boot(demo_ids, partner_pack=_PACK)
    first = await _pack_demo_count(boot_factory)
    await install_demo_projects_at_boot(demo_ids, partner_pack=_PACK)

    assert first == len(demo_ids)
    assert await _pack_demo_count(boot_factory) == first


async def test_a_fast_test_start_with_a_pack_active_seeds_no_pack_demos(boot_factory, monkeypatch) -> None:
    from app.core.partner_pack.discovery import get_pack_by_slug, reset_cache
    from app.main import _seed_demo_account

    if get_pack_by_slug(_PACK) is None:
        pytest.skip(f"{_PACK} is not discoverable in this layout")
    monkeypatch.setenv("SEED_DEMO", "true")
    monkeypatch.setenv("OE_TEST_FAST_STARTUP", "1")
    monkeypatch.setenv("OE_PACK", _PACK)
    reset_cache()
    try:
        await _seed_demo_account()
        await _seed_demo_account()
    finally:
        monkeypatch.delenv("OE_PACK")
        reset_cache()

    assert await _pack_demo_count(boot_factory) == 0
