"""Unit tests for Asset Register (BIMElement.asset_info, v2.3.0).

Covers the repository-level merge / auto-flag logic only — avoids the
full app lifespan because SQLAlchemy models can be exercised in
isolation against an in-memory SQLite DB. Router-level tests live in
``tests/integration/`` so they share the fuller auth fixtures.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.bim_hub.models import BIMElement, BIMModel, BOQElementLink
from app.modules.bim_hub.repository import BIMElementRepository


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Fresh in-memory SQLite — per-test isolation.

    Scoped ``create_all(tables=[...])`` because running the full unit
    suite pulls other modules onto ``Base.metadata`` with FKs to tables
    we don't care about here (e.g. ``oe_projects_project``). Listing only
    the two tables we actually use keeps this test self-contained and
    immune to ordering when the whole suite runs.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                BIMModel.__table__,
                BIMElement.__table__,
                # BIMElement.boq_links is eagerly loaded (lazy="selectin")
                # so session.refresh() queries it — the table must exist
                # even if we never insert rows.
                BOQElementLink.__table__,
            ],
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _seed_element(session: AsyncSession, **overrides) -> BIMElement:
    """Insert one model + one element. Returns the element."""
    project_id = overrides.pop("project_id", uuid.uuid4())
    model = BIMModel(
        project_id=project_id,
        name=overrides.pop("model_name", "Test Model"),
        status="ready",
    )
    session.add(model)
    await session.flush()
    element = BIMElement(
        model_id=model.id,
        stable_id=overrides.pop("stable_id", "elem-001"),
        element_type=overrides.pop("element_type", "Pump"),
        name=overrides.pop("name", "AHU-01"),
        **overrides,
    )
    session.add(element)
    await session.flush()
    await session.refresh(element)
    return element


class TestAssetInfoMerge:
    @pytest.mark.asyncio
    async def test_first_write_flips_tracked_flag(self, session):
        element = await _seed_element(session)
        assert element.is_tracked_asset is False

        repo = BIMElementRepository(session)
        updated = await repo.update_asset_info(
            element.id,
            asset_info={"manufacturer": "Siemens", "model": "SV-100"},
        )
        assert updated is not None
        assert updated.is_tracked_asset is True
        assert updated.asset_info == {"manufacturer": "Siemens", "model": "SV-100"}

    @pytest.mark.asyncio
    async def test_partial_update_preserves_existing_keys(self, session):
        element = await _seed_element(
            session, asset_info={"manufacturer": "Siemens", "serial_number": "SN123"}
        )
        # Pre-existing write manually flipped the flag so the fixture
        # mimics a row that was already registered.
        element.is_tracked_asset = True
        await session.flush()

        repo = BIMElementRepository(session)
        updated = await repo.update_asset_info(
            element.id,
            asset_info={"warranty_until": "2027-12-31"},
        )
        assert updated.asset_info == {
            "manufacturer": "Siemens",
            "serial_number": "SN123",
            "warranty_until": "2027-12-31",
        }

    @pytest.mark.asyncio
    async def test_none_and_empty_string_clear_keys(self, session):
        element = await _seed_element(
            session,
            asset_info={"manufacturer": "Siemens", "serial_number": "SN123"},
            is_tracked_asset=True,
        )
        repo = BIMElementRepository(session)
        updated = await repo.update_asset_info(
            element.id,
            asset_info={"manufacturer": None, "serial_number": ""},
        )
        # Both cleared; asset_info becomes empty — tracked flag kept
        # because caller did not ask to clear it.
        assert updated.asset_info == {}
        assert updated.is_tracked_asset is True

    @pytest.mark.asyncio
    async def test_explicit_flag_override_beats_auto(self, session):
        element = await _seed_element(session)
        repo = BIMElementRepository(session)
        updated = await repo.update_asset_info(
            element.id,
            asset_info={"manufacturer": "Siemens"},
            is_tracked_asset=False,
        )
        # Even though asset_info is non-empty, caller forced False.
        assert updated.is_tracked_asset is False

    @pytest.mark.asyncio
    async def test_missing_element_returns_none(self, session):
        repo = BIMElementRepository(session)
        missing = uuid.uuid4()
        result = await repo.update_asset_info(
            missing, asset_info={"manufacturer": "ACME"}
        )
        assert result is None


class TestListTrackedAssets:
    @pytest.mark.asyncio
    async def test_excludes_untracked_elements(self, session):
        project_id = uuid.uuid4()
        # One tracked + one untracked in same project.
        await _seed_element(
            session,
            project_id=project_id,
            stable_id="tracked-1",
            asset_info={"manufacturer": "Siemens"},
            is_tracked_asset=True,
        )
        await _seed_element(
            session,
            project_id=project_id,
            stable_id="untracked-1",
            model_name="Other Model",
        )
        repo = BIMElementRepository(session)
        rows, total = await repo.list_tracked_assets_for_project(project_id)
        assert total == 1
        assert len(rows) == 1
        assert rows[0][0].stable_id == "tracked-1"

    @pytest.mark.asyncio
    async def test_search_matches_manufacturer_via_json(self, session):
        project_id = uuid.uuid4()
        await _seed_element(
            session,
            project_id=project_id,
            stable_id="pump-1",
            asset_info={"manufacturer": "Grundfos"},
            is_tracked_asset=True,
        )
        await _seed_element(
            session,
            project_id=project_id,
            stable_id="pump-2",
            model_name="m2",
            asset_info={"manufacturer": "Siemens"},
            is_tracked_asset=True,
        )
        repo = BIMElementRepository(session)
        rows, total = await repo.list_tracked_assets_for_project(
            project_id, search="grund"
        )
        assert total == 1
        assert rows[0][0].stable_id == "pump-1"

    @pytest.mark.asyncio
    async def test_operational_status_filter(self, session):
        project_id = uuid.uuid4()
        await _seed_element(
            session,
            project_id=project_id,
            stable_id="a",
            asset_info={"operational_status": "operational"},
            is_tracked_asset=True,
        )
        await _seed_element(
            session,
            project_id=project_id,
            stable_id="b",
            model_name="m2",
            asset_info={"operational_status": "under_maintenance"},
            is_tracked_asset=True,
        )
        repo = BIMElementRepository(session)
        rows, total = await repo.list_tracked_assets_for_project(
            project_id, operational_status="under_maintenance"
        )
        assert total == 1
        assert rows[0][0].stable_id == "b"

    @pytest.mark.asyncio
    async def test_project_isolation(self, session):
        project_a = uuid.uuid4()
        project_b = uuid.uuid4()
        await _seed_element(
            session, project_id=project_a, is_tracked_asset=True,
            asset_info={"manufacturer": "A"},
        )
        await _seed_element(
            session, project_id=project_b, is_tracked_asset=True,
            model_name="B-model", stable_id="b-asset",
            asset_info={"manufacturer": "B"},
        )
        repo = BIMElementRepository(session)
        rows_a, total_a = await repo.list_tracked_assets_for_project(project_a)
        rows_b, total_b = await repo.list_tracked_assets_for_project(project_b)
        assert total_a == 1
        assert total_b == 1
        assert rows_a[0][1].project_id == project_a
        assert rows_b[0][1].project_id == project_b
