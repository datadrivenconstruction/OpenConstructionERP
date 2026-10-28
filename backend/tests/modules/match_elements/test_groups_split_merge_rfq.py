# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service-level tests for split_group / merge_groups / no_match(rfq).

These exercise the group-operation methods that used to raise
``NotImplementedError("Phase A.5b")`` plus the RFQ wiring that replaced
the "procurement integration pending" placeholder note. They run against
the conftest-provisioned PostgreSQL database seeded with a BIM model +
elements, driving the service directly (the router merely forwards to
these methods, so the service is the load-bearing surface).

Consistency is the key invariant under test: after a split or merge the
sum of element counts and quantities across the affected groups must
equal what it was before, and the session must contain no orphaned or
duplicated element ids.

Run:
    cd backend
    python -m pytest tests/modules/match_elements/test_groups_split_merge_rfq.py -q
"""

from __future__ import annotations

import uuid

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

# Eager-import the model namespaces the suite touches so create_all sees a
# coherent table set (mirrors test_match_elements_api.py).
import app.modules.bim_hub.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.costs.models  # noqa: E402,F401
import app.modules.match_elements.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.rfq_bidding.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401
from app.modules.match_elements import schemas  # noqa: E402
from app.modules.match_elements.service import get_service  # noqa: E402


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _create_schema():
    """Create all tables on the conftest-provisioned PostgreSQL database.

    We deliberately do NOT boot the full app lifespan here - these tests
    drive the service layer directly (no HTTP, no auth dependency), so we
    only need the schema.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


async def _seed_project_with_bim(n_walls: int = 3, n_slabs: int = 1) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a Project + BIMModel + walls and slabs. Returns (project, model)."""
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    project_id = uuid.uuid4()
    model_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    async with async_session_factory() as s:
        # Project.owner_id FKs oe_users_user - seed + flush the user first
        # so the FK is satisfied regardless of SQLAlchemy's insert order.
        s.add(
            User(
                id=owner_id,
                email=f"owner-{owner_id.hex[:8]}@me-groups.test",
                hashed_password="x",
                full_name="ME Groups Owner",
                role="admin",
                is_active=True,
            )
        )
        await s.flush()
        s.add(
            Project(
                id=project_id,
                name=f"ME-Groups-{uuid.uuid4().hex[:6]}",
                description="split/merge test",
                owner_id=owner_id,
                currency="EUR",
                classification_standard="din276",
                metadata_={},
                fx_rates=[],
            )
        )
        s.add(
            BIMModel(
                id=model_id,
                project_id=project_id,
                name="test.ifc",
                model_format="ifc",
                version="1",
                status="completed",
                element_count=n_walls + n_slabs,
                storey_count=1,
                metadata_={},
            )
        )
        # Walls share ifc_class + type_name so they land in ONE group under
        # the default ["ifc_class","type_name"] composite key.
        for i in range(n_walls):
            s.add(
                BIMElement(
                    id=uuid.uuid4(),
                    model_id=model_id,
                    stable_id=f"wall-{i:03d}",
                    element_type="IfcWallStandardCase",
                    name=f"Wall_{i}",
                    storey="Level 01",
                    discipline="ARCH",
                    properties={"type_name": "Generic Wall 240mm", "material": "Concrete C30/37"},
                    quantities={"volume_m3": 10.0, "area_m2": 40.0, "count": 1.0},
                    metadata_={},
                    asset_info={},
                    is_tracked_asset=False,
                )
            )
        for i in range(n_slabs):
            s.add(
                BIMElement(
                    id=uuid.uuid4(),
                    model_id=model_id,
                    stable_id=f"slab-{i:03d}",
                    element_type="IfcSlab",
                    name=f"Slab_{i}",
                    storey="Level 01",
                    discipline="STRUCT",
                    properties={"type_name": "Generic Slab 200mm", "material": "Concrete C25/30"},
                    quantities={"volume_m3": 20.0, "area_m2": 100.0, "count": 1.0},
                    metadata_={},
                    asset_info={},
                    is_tracked_asset=False,
                )
            )
        await s.commit()
    return project_id, model_id


async def _new_session_with_groups(project_id: uuid.UUID, model_id: uuid.UUID):
    """Create a session and rebuild its groups. Returns the session_id."""
    from app.database import async_session_factory

    svc = get_service()
    async with async_session_factory() as s:
        created = await svc.create_session(
            s,
            schemas.SessionCreate(project_id=project_id, bim_model_id=model_id, source="bim"),
        )
        await s.commit()
        session_id = created.id
    async with async_session_factory() as s:
        await svc.rebuild_groups(s, session_id)
        await s.commit()
    return session_id


def _wall_group(groups) -> schemas.GroupSummary:
    for g in groups.groups:
        if "IfcWall" in g.group_key:
            return g
    raise AssertionError("no wall group found")


# ── split_group ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_split_group_moves_subset_and_keeps_totals():
    from app.database import async_session_factory

    svc = get_service()
    project_id, model_id = await _seed_project_with_bim(n_walls=3, n_slabs=1)
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    wall = _wall_group(groups)
    assert wall.element_count == 3
    assert wall.quantities["volume_m3"] == 30.0

    # Read the wall group's element ids, split one out.
    async with async_session_factory() as s:
        detail = await svc.get_group_detail(s, session_id, wall.group_key)
    move_id = detail.element_ids[0]

    async with async_session_factory() as s:
        new_detail = await svc.split_group(
            s,
            session_id,
            wall.group_key,
            schemas.GroupSplitRequest(new_group_key="ifc_class:IfcWall|type_name:Split", element_ids=[move_id]),
        )
        await s.commit()

    # New group has the one moved element; status is a fresh "unmatched".
    assert new_detail.element_count == 1
    assert new_detail.element_ids == [move_id]
    assert new_detail.quantities["volume_m3"] == 10.0
    assert new_detail.status == "unmatched"

    # Source group shrank to 2 elements / 20 m3, and the session total is
    # conserved (2 + 1 == original 3; 20 + 10 == original 30).
    async with async_session_factory() as s:
        src_detail = await svc.get_group_detail(s, session_id, wall.group_key)
    assert src_detail.element_count == 2
    assert src_detail.quantities["volume_m3"] == 20.0
    assert move_id not in src_detail.element_ids


@pytest.mark.asyncio
async def test_split_group_rejects_empty_and_full_and_unknown():
    from fastapi import HTTPException

    from app.database import async_session_factory

    svc = get_service()
    project_id, model_id = await _seed_project_with_bim(n_walls=2, n_slabs=0)
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    wall = _wall_group(groups)
    async with async_session_factory() as s:
        detail = await svc.get_group_detail(s, session_id, wall.group_key)
    all_ids = detail.element_ids

    # Empty subset → 422.
    async with async_session_factory() as s:
        with pytest.raises(HTTPException) as ei:
            await svc.split_group(
                s, session_id, wall.group_key, schemas.GroupSplitRequest(new_group_key="x", element_ids=[])
            )
        assert ei.value.status_code == 422

    # Moving every element out (would empty the source) → 422.
    async with async_session_factory() as s:
        with pytest.raises(HTTPException) as ei:
            await svc.split_group(
                s, session_id, wall.group_key, schemas.GroupSplitRequest(new_group_key="x", element_ids=all_ids)
            )
        assert ei.value.status_code == 422

    # Unknown element id → 422.
    async with async_session_factory() as s:
        with pytest.raises(HTTPException) as ei:
            await svc.split_group(
                s,
                session_id,
                wall.group_key,
                schemas.GroupSplitRequest(new_group_key="x", element_ids=["not-a-real-id"]),
            )
        assert ei.value.status_code == 422


# ── merge_groups ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_groups_unions_and_recomputes():
    from app.database import async_session_factory

    svc = get_service()
    project_id, model_id = await _seed_project_with_bim(n_walls=3, n_slabs=1)
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    keys = [g.group_key for g in groups.groups]
    wall_key = next(k for k in keys if "IfcWall" in k)
    slab_key = next(k for k in keys if "IfcSlab" in k)

    total_before = sum(g.element_count for g in groups.groups)
    vol_before = sum(g.quantities.get("volume_m3", 0.0) for g in groups.groups)

    async with async_session_factory() as s:
        merged = await svc.merge_groups(
            s,
            session_id,
            wall_key,
            schemas.GroupMergeRequest(other_group_key=slab_key),
        )
        await s.commit()

    # Merged group carries all 4 elements and the combined volume.
    assert merged.element_count == total_before == 4
    assert merged.quantities["volume_m3"] == pytest.approx(vol_before)
    assert merged.quantities["volume_m3"] == pytest.approx(30.0 + 20.0)

    # The slab group is gone; the session now has exactly one group with
    # all the elements (no orphans, no dupes).
    async with async_session_factory() as s:
        groups_after = await svc.list_groups(s, session_id)
    assert len(groups_after.groups) == 1
    assert groups_after.groups[0].element_count == 4
    # No duplicate element ids survived the merge.
    async with async_session_factory() as s:
        merged_detail = await svc.get_group_detail(s, session_id, merged.group_key)
    assert len(merged_detail.element_ids) == len(set(merged_detail.element_ids)) == 4


@pytest.mark.asyncio
async def test_merge_with_rename_and_self_merge_rejected():
    from fastapi import HTTPException

    from app.database import async_session_factory

    svc = get_service()
    project_id, model_id = await _seed_project_with_bim(n_walls=2, n_slabs=1)
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    wall_key = next(g.group_key for g in groups.groups if "IfcWall" in g.group_key)
    slab_key = next(g.group_key for g in groups.groups if "IfcSlab" in g.group_key)

    # Self-merge → 422.
    async with async_session_factory() as s:
        with pytest.raises(HTTPException) as ei:
            await svc.merge_groups(s, session_id, wall_key, schemas.GroupMergeRequest(other_group_key=wall_key))
        assert ei.value.status_code == 422

    # Merge with a rename to a brand-new key.
    async with async_session_factory() as s:
        merged = await svc.merge_groups(
            s,
            session_id,
            wall_key,
            schemas.GroupMergeRequest(other_group_key=slab_key, new_group_key="merged:all-concrete"),
        )
        await s.commit()
    assert merged.group_key == "merged:all-concrete"
    assert merged.element_count == 3

    # Merging a non-existent group → 404.
    async with async_session_factory() as s:
        with pytest.raises(HTTPException) as ei:
            await svc.merge_groups(
                s, session_id, "merged:all-concrete", schemas.GroupMergeRequest(other_group_key="nope:nope")
            )
        assert ei.value.status_code == 404


# ── no_match(rfq) ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_match_rfq_creates_real_rfq():
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.rfq_bidding.models import RFQ

    svc = get_service()
    project_id, model_id = await _seed_project_with_bim(n_walls=2, n_slabs=0)
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    wall_key = _wall_group(groups).group_key

    async with async_session_factory() as s:
        detail = await svc.no_match(
            s,
            session_id,
            schemas.NoMatchRequest(group_key=wall_key, action="rfq"),
        )
        await s.commit()

    # The group is flagged tbd and the note references a real RFQ number -
    # NOT the old "procurement integration pending" placeholder.
    assert detail.status == "tbd"
    assert detail.notes is not None
    assert "RFQ" in detail.notes
    assert "pending" not in detail.notes.lower()

    # A real RFQ row was created for this project, tagged back to the
    # match session + group so the UI can deep-link.
    async with async_session_factory() as s:
        rfqs = (await s.execute(select(RFQ).where(RFQ.project_id == project_id))).scalars().all()
    assert len(rfqs) == 1
    rfq = rfqs[0]
    assert rfq.status == "draft"
    assert rfq.currency_code == "EUR"
    assert rfq.metadata_.get("match_group_key") == wall_key
    assert rfq.metadata_.get("match_session_id") == str(session_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
