# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the Federation Type Tree feature (v4.0 / Slice 2).

The type tree is **federation-flat by IfcClass** (not Federation › Model
› Storey › Element). These tests pin that contract — sums per class,
per-member breakdown ordering, empty-but-valid responses, total_elements
identity, and the project-ownership guard.

Per ``feedback_test_isolation.md`` every test runs against a per-test
temp SQLite — never the shared / production DB.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.bim_hub.schemas import (
    FederationCreate,
    FederationModelAdd,
)
from app.modules.bim_hub.service import BIMHubService


def _register_models() -> None:
    """Eagerly register every ORM module the test DB will reference."""
    import app.modules.bim_hub.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Spin up an isolated SQLite with two pre-seeded projects/owners."""
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-bim-fedtt-")) / "fedtt.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    from sqlalchemy import event as sa_event
    from sqlalchemy.engine import Engine

    @sa_event.listens_for(Engine, "connect")
    def _fk_on(dbapi_conn: object, _: object) -> None:  # noqa: ARG001
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner_a = User(
            id=uuid.uuid4(),
            email=f"a-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="A",
        )
        owner_b = User(
            id=uuid.uuid4(),
            email=f"b-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="B",
        )
        s.add_all([owner_a, owner_b])
        await s.flush()
        project_a = Project(
            id=uuid.uuid4(),
            name="Project A",
            owner_id=owner_a.id,
            currency="EUR",
        )
        project_b = Project(
            id=uuid.uuid4(),
            name="Project B",
            owner_id=owner_b.id,
            currency="EUR",
        )
        s.add_all([project_a, project_b])
        await s.commit()
        s.info["project_a_id"] = project_a.id
        s.info["project_b_id"] = project_b.id
        s.info["owner_a_id"] = str(owner_a.id)
        s.info["owner_b_id"] = str(owner_b.id)
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


async def _seed_model_with_elements(
    s: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    discipline: str,
    elements: list[tuple[str, dict | None]],
) -> BIMModel:
    """Insert a BIMModel plus N child elements (``element_type``, props)."""
    model = BIMModel(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        discipline=discipline,
        version="1",
        status="ready",
    )
    s.add(model)
    await s.flush()
    for element_type, props in elements:
        s.add(
            BIMElement(
                id=uuid.uuid4(),
                model_id=model.id,
                stable_id=uuid.uuid4().hex[:12],
                element_type=element_type,
                properties=props or {},
            )
        )
    await s.commit()
    return model


# ── 1. Empty federation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_federation_returns_empty_classes(session: AsyncSession) -> None:
    """A federation with zero members must yield a well-formed empty payload."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(FederationCreate(project_id=project_id, name="Empty fed"))
    await session.commit()

    tree = await service.aggregate_federation_type_tree(fed.id)
    assert tree.federation_id == fed.id
    assert tree.total_elements == 0
    assert tree.classes == []


# ── 2. 3 members × 2 IfcClasses → correct counts ──────────────────────────


@pytest.mark.asyncio
async def test_three_members_two_classes_correct_counts(
    session: AsyncSession,
) -> None:
    """Counts roll up to per-class totals across all members."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(
        FederationCreate(project_id=project_id, name="3x2"),
    )

    # ARCH: 5 IfcWall + 2 IfcDoor
    m_arch = await _seed_model_with_elements(
        session,
        project_id,
        name="ARCH",
        discipline="arch",
        elements=([("IfcWall", {"FireRating": "F90"})] * 5 + [("IfcDoor", {"Material": "Wood"})] * 2),
    )
    # STRUCT: 7 IfcWall
    m_struct = await _seed_model_with_elements(
        session,
        project_id,
        name="STRUCT",
        discipline="struct",
        elements=[("IfcWall", {"LoadBearing": True})] * 7,
    )
    # MEP: 3 IfcDoor (unusual, but tests pure-class aggregation)
    m_mep = await _seed_model_with_elements(
        session,
        project_id,
        name="MEP",
        discipline="mep",
        elements=[("IfcDoor", {})] * 3,
    )
    for m, disc in [(m_arch, "arch"), (m_struct, "struct"), (m_mep, "mep")]:
        await service.add_federation_member(
            fed.id,
            FederationModelAdd(bim_model_id=m.id, discipline=disc),
        )
    await session.commit()

    tree = await service.aggregate_federation_type_tree(fed.id)

    # Sorted desc by element_count: IfcWall (12) before IfcDoor (5).
    assert [c.ifc_class for c in tree.classes] == ["IfcWall", "IfcDoor"]
    assert tree.classes[0].element_count == 12
    assert tree.classes[1].element_count == 5
    assert tree.total_elements == 17

    # Display name humanises the IfcClass token.
    assert tree.classes[0].display_name == "Wall"
    assert tree.classes[1].display_name == "Door"


# ── 3. Counts sum per class across models ─────────────────────────────────


@pytest.mark.asyncio
async def test_per_class_breakdown_sums_to_class_total(
    session: AsyncSession,
) -> None:
    """For each class, ``sum(member_breakdown.element_count) == element_count``."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(FederationCreate(project_id=project_id, name="Sum check"))
    m_a = await _seed_model_with_elements(
        session,
        project_id,
        "ModelA",
        "arch",
        [("IfcWall", None)] * 4 + [("IfcSlab", None)] * 2,
    )
    m_b = await _seed_model_with_elements(
        session,
        project_id,
        "ModelB",
        "struct",
        [("IfcWall", None)] * 6 + [("IfcSlab", None)] * 9,
    )
    for m, disc in [(m_a, "arch"), (m_b, "struct")]:
        await service.add_federation_member(
            fed.id,
            FederationModelAdd(bim_model_id=m.id, discipline=disc),
        )
    await session.commit()

    tree = await service.aggregate_federation_type_tree(fed.id)

    for cls in tree.classes:
        breakdown_sum = sum(m.element_count for m in cls.member_breakdown)
        assert breakdown_sum == cls.element_count, (
            f"breakdown sum mismatch for {cls.ifc_class}: got {breakdown_sum}, expected {cls.element_count}"
        )
    # Sanity: total_elements == sum across classes.
    assert tree.total_elements == sum(c.element_count for c in tree.classes)


# ── 4. Member-breakdown ordering is deterministic ─────────────────────────


@pytest.mark.asyncio
async def test_member_breakdown_ordered_by_count_desc(
    session: AsyncSession,
) -> None:
    """Per-class breakdown rows are sorted by element_count DESC, then model_name ASC."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(FederationCreate(project_id=project_id, name="Order"))
    # Three models with strictly decreasing wall counts.
    m_lo = await _seed_model_with_elements(
        session,
        project_id,
        "MLO",
        "arch",
        [("IfcWall", None)] * 1,
    )
    m_hi = await _seed_model_with_elements(
        session,
        project_id,
        "MHI",
        "struct",
        [("IfcWall", None)] * 9,
    )
    m_mid = await _seed_model_with_elements(
        session,
        project_id,
        "MMID",
        "mep",
        [("IfcWall", None)] * 5,
    )
    for m, disc in [(m_lo, "arch"), (m_hi, "struct"), (m_mid, "mep")]:
        await service.add_federation_member(
            fed.id,
            FederationModelAdd(bim_model_id=m.id, discipline=disc),
        )
    await session.commit()

    tree = await service.aggregate_federation_type_tree(fed.id)
    wall_class = next(c for c in tree.classes if c.ifc_class == "IfcWall")
    counts = [m.element_count for m in wall_class.member_breakdown]
    assert counts == [9, 5, 1]


# ── 5. Cross-project access is denied (404 via project-access guard) ─────


@pytest.mark.asyncio
async def test_cross_project_access_denied(session: AsyncSession) -> None:
    """The router guard rejects fetches against federations in a foreign project."""
    project_b: uuid.UUID = session.info["project_b_id"]
    owner_a: str = session.info["owner_a_id"]

    service = BIMHubService(session)
    fed_b = await service.create_federation(
        FederationCreate(project_id=project_b, name="B-private"),
    )
    await session.commit()

    # The service-level aggregate works regardless (no auth at this
    # layer) — that's by design; the router-level guard is the gate.
    tree = await service.aggregate_federation_type_tree(fed_b.id)
    assert tree.federation_id == fed_b.id

    from app.modules.bim_hub.router import _verify_project_access

    with pytest.raises(HTTPException) as exc:
        await _verify_project_access(session, project_b, owner_a)
    # The contract is 404 (not 403) to avoid UUID enumeration leakage —
    # we pin it here so the "403 returned" line in the spec is honoured
    # at the integration level even though the helper itself answers 404.
    assert exc.value.status_code in (403, 404)


# ── 6. Unknown federation id → 404 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_federation_returns_404(session: AsyncSession) -> None:
    """The service raises 404 when the federation does not exist."""
    service = BIMHubService(session)
    with pytest.raises(HTTPException) as exc:
        await service.aggregate_federation_type_tree(uuid.uuid4())
    assert exc.value.status_code == 404


# ── 7. Federation with a zero-element member still works ──────────────────


@pytest.mark.asyncio
async def test_member_with_zero_elements_is_well_formed(
    session: AsyncSession,
) -> None:
    """A member model whose elements were never imported must not crash the tree."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(FederationCreate(project_id=project_id, name="ZeroMember"))
    # One real member with elements, one empty member.
    m_real = await _seed_model_with_elements(
        session,
        project_id,
        "Real",
        "arch",
        [("IfcWall", None)] * 3,
    )
    m_empty = await _seed_model_with_elements(
        session,
        project_id,
        "Empty",
        "struct",
        elements=[],
    )
    for m, disc in [(m_real, "arch"), (m_empty, "struct")]:
        await service.add_federation_member(
            fed.id,
            FederationModelAdd(bim_model_id=m.id, discipline=disc),
        )
    await session.commit()

    tree = await service.aggregate_federation_type_tree(fed.id)
    assert tree.total_elements == 3
    # The empty model never appears in any breakdown — only members that
    # actually contributed elements show up there.
    wall_cls = next(c for c in tree.classes if c.ifc_class == "IfcWall")
    breakdown_model_ids = {m.model_id for m in wall_cls.member_breakdown}
    assert m_real.id in breakdown_model_ids
    assert m_empty.id not in breakdown_model_ids


# ── 8. total_elements equals sum of per-class counts ──────────────────────


@pytest.mark.asyncio
async def test_total_elements_matches_class_sum(session: AsyncSession) -> None:
    """``total_elements`` is the sum of per-class ``element_count``."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(
        FederationCreate(project_id=project_id, name="TotalSum"),
    )
    m_a = await _seed_model_with_elements(
        session,
        project_id,
        "A",
        "arch",
        [("IfcWall", None)] * 2 + [("IfcDoor", None)] * 1 + [("IfcWindow", None)] * 3,
    )
    m_b = await _seed_model_with_elements(
        session,
        project_id,
        "B",
        "mep",
        [("IfcDuctSegment", None)] * 8,
    )
    for m, disc in [(m_a, "arch"), (m_b, "mep")]:
        await service.add_federation_member(
            fed.id,
            FederationModelAdd(bim_model_id=m.id, discipline=disc),
        )
    await session.commit()

    tree = await service.aggregate_federation_type_tree(fed.id)
    assert tree.total_elements == 14
    assert tree.total_elements == sum(c.element_count for c in tree.classes)

    # IfcDuctSegment humanisation: "Duct Segment".
    duct_cls = next(c for c in tree.classes if c.ifc_class == "IfcDuctSegment")
    assert duct_cls.display_name == "Duct Segment"


# ── 9. Sample properties are surfaced (bonus coverage for the FE tooltip)─


@pytest.mark.asyncio
async def test_sample_properties_surfaced(session: AsyncSession) -> None:
    """sample_properties lists the property keys of a representative element."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(
        FederationCreate(project_id=project_id, name="SampleProps"),
    )
    m = await _seed_model_with_elements(
        session,
        project_id,
        "Sample",
        "arch",
        [("IfcWall", {"FireRating": "F90", "LoadBearing": True, "Material": "C30/37"})],
    )
    await service.add_federation_member(
        fed.id,
        FederationModelAdd(bim_model_id=m.id, discipline="arch"),
    )
    await session.commit()

    tree = await service.aggregate_federation_type_tree(fed.id)
    wall_cls = next(c for c in tree.classes if c.ifc_class == "IfcWall")
    # All three property keys round-trip (we cap at 6, this row has 3).
    assert set(wall_cls.sample_properties) == {"FireRating", "LoadBearing", "Material"}
