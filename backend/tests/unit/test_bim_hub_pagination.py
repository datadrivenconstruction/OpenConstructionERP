"""Pagination / guard-cap tests for :mod:`app.modules.bim_hub.service`.

Scope:
    - ``list_element_groups`` is a public reader that now paginates
      (limit defaulting to 500, clamped to ``MAX_BIM_HUB_ROWS``). We
      verify the 500-default, an explicit 1000 override, and the upper
      clamp semantics.
    - ``_resolve_members_for_group`` is the dynamic-group resolver that
      MUST load every match for correctness. We seed more elements than
      the cap allows and assert a ``WARNING`` is logged when the guard
      trips.

Backed by an in-memory aiosqlite DB with a scoped ``create_all`` so the
test does not require the full app lifespan.
"""
from __future__ import annotations

import logging
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.bim_hub.models import (
    BIMElement,
    BIMElementGroup,
    BIMModel,
    BOQElementLink,
)
from app.modules.bim_hub.service import MAX_BIM_HUB_ROWS, BIMHubService

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Fresh in-memory SQLite per test.

    Scoped ``create_all`` avoids pulling unrelated modules' FKs into the
    test universe.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                BIMModel.__table__,
                BIMElement.__table__,
                BIMElementGroup.__table__,
                # BIMElement.boq_links is eagerly loaded; the table must
                # exist even when we never insert rows (mirrors the
                # existing bim_asset_register test fixture).
                BOQElementLink.__table__,
            ],
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s
    await engine.dispose()


async def _seed_model(session: AsyncSession) -> BIMModel:
    model = BIMModel(
        project_id=uuid.uuid4(),
        name="Pagination Model",
        status="ready",
    )
    session.add(model)
    await session.flush()
    return model


async def _bulk_insert_elements(
    session: AsyncSession, model_id: uuid.UUID, count: int, element_type: str = "Wall"
) -> None:
    rows = [
        BIMElement(
            model_id=model_id,
            stable_id=f"elem-{i:06d}",
            element_type=element_type,
            name=f"E-{i:06d}",
        )
        for i in range(count)
    ]
    session.add_all(rows)
    await session.flush()


async def _bulk_insert_groups(
    session: AsyncSession, project_id: uuid.UUID, count: int
) -> None:
    rows = [
        BIMElementGroup(
            project_id=project_id,
            name=f"grp-{i:05d}",
            is_dynamic=False,
            element_ids=[],
            element_count=0,
            filter_criteria={},
        )
        for i in range(count)
    ]
    session.add_all(rows)
    await session.flush()


# ── list_element_groups pagination ────────────────────────────────────────


class TestListElementGroupsPagination:
    @pytest.mark.asyncio
    async def test_default_limit_is_500(self, session):
        model = await _seed_model(session)
        await _bulk_insert_groups(session, model.project_id, count=600)

        service = BIMHubService(session)
        rows = await service.list_element_groups(model.project_id)

        assert len(rows) == 500

    @pytest.mark.asyncio
    async def test_explicit_limit_1000_returns_1000(self, session):
        model = await _seed_model(session)
        await _bulk_insert_groups(session, model.project_id, count=1200)

        service = BIMHubService(session)
        rows = await service.list_element_groups(model.project_id, limit=1000)

        assert len(rows) == 1000

    @pytest.mark.asyncio
    async def test_limit_clamped_to_max(self, session):
        """A caller passing a ridiculous limit gets clamped at MAX_BIM_HUB_ROWS.

        No silent fallback — we still serve what the cap allows, and the
        clamp is deterministic so the response size is predictable for
        downstream consumers.
        """
        model = await _seed_model(session)
        # Seed (MAX + 10) groups so we can distinguish clamped vs uncapped.
        await _bulk_insert_groups(
            session, model.project_id, count=MAX_BIM_HUB_ROWS + 10
        )

        service = BIMHubService(session)
        rows = await service.list_element_groups(
            model.project_id, limit=MAX_BIM_HUB_ROWS * 10
        )

        assert len(rows) == MAX_BIM_HUB_ROWS

    @pytest.mark.asyncio
    async def test_offset_walks_cleanly(self, session):
        model = await _seed_model(session)
        await _bulk_insert_groups(session, model.project_id, count=1200)

        service = BIMHubService(session)
        page1 = await service.list_element_groups(
            model.project_id, offset=0, limit=500
        )
        page2 = await service.list_element_groups(
            model.project_id, offset=500, limit=500
        )
        page3 = await service.list_element_groups(
            model.project_id, offset=1000, limit=500
        )

        ids = {g.id for g in page1} | {g.id for g in page2} | {g.id for g in page3}
        assert len(ids) == 1200  # no overlap, no gaps


# ── _resolve_members_for_group guard cap ──────────────────────────────────


class TestResolveMembersForGroupGuardCap:
    @pytest.mark.asyncio
    async def test_over_cap_logs_warning(self, session, caplog, monkeypatch):
        """Seed > cap matching elements and trigger a dynamic-group resolve.

        We shrink ``MAX_BIM_HUB_ROWS`` via monkeypatch so the fixture stays
        fast.  The production constant is exercised by
        ``test_limit_clamped_to_max``.
        """
        from app.modules.bim_hub import service as bim_service

        monkeypatch.setattr(bim_service, "MAX_BIM_HUB_ROWS", 10)

        model = await _seed_model(session)
        # Seed 15 elements all matching the filter.
        await _bulk_insert_elements(
            session, model.id, count=15, element_type="Wall"
        )

        group = BIMElementGroup(
            project_id=model.project_id,
            model_id=model.id,
            name="dyn-walls",
            is_dynamic=True,
            filter_criteria={"element_type": "Wall"},
            element_ids=[],
            element_count=0,
        )
        session.add(group)
        await session.flush()

        service = BIMHubService(session)
        caplog.set_level(logging.WARNING, logger=bim_service.logger.name)

        members = await service._resolve_members_for_group(group)

        # Cap in effect → resolver returns at most MAX (= 10 here).
        assert len(members) == 10

        warnings = [
            rec
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "MAX_BIM_HUB_ROWS=10" in rec.getMessage()
            and "member list is incomplete" in rec.getMessage()
        ]
        assert warnings, "Expected a WARNING log from the group-resolve guard cap"

    @pytest.mark.asyncio
    async def test_under_cap_no_warning(self, session, caplog, monkeypatch):
        """Under-cap resolves must NOT emit a warning."""
        from app.modules.bim_hub import service as bim_service

        monkeypatch.setattr(bim_service, "MAX_BIM_HUB_ROWS", 50)

        model = await _seed_model(session)
        await _bulk_insert_elements(session, model.id, count=5, element_type="Slab")

        group = BIMElementGroup(
            project_id=model.project_id,
            model_id=model.id,
            name="dyn-slabs",
            is_dynamic=True,
            filter_criteria={"element_type": "Slab"},
            element_ids=[],
            element_count=0,
        )
        session.add(group)
        await session.flush()

        service = BIMHubService(session)
        caplog.set_level(logging.WARNING, logger=bim_service.logger.name)

        members = await service._resolve_members_for_group(group)

        assert len(members) == 5
        assert not [
            rec
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "MAX_BIM_HUB_ROWS" in rec.getMessage()
        ]
