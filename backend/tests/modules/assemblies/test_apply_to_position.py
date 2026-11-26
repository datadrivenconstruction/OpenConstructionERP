"""Insert an assembly into an existing BOQ position.

Worked example: an interior partition priced from a recipe.

* Assembly "Gypsum partition", per m2: board 2.1 m2 at 4.00 (8.40) and labour
  0.35 h at 60.00 (21.00), so 29.40 per m2.
* Position "Interior partition", 120 m2 at a hand-typed 25.00 (3,000.00).

Replace at factor 1 gives 29.40 and 3,528.00; factor 1.1 (ten per cent extra
board and labour) gives 32.34; adding to a position that already carries paint
at 3.00 gives 32.40. A preview never writes, and a locked bill refuses the apply.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError

from tests._pg import transactional_session

OWNER = uuid.uuid4()
STRANGER = uuid.uuid4()
PROJECT = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        for uid, email in [(OWNER, "asm-pos-a@test.io"), (STRANGER, "asm-pos-b@test.io")]:
            s.add(User(id=uid, email=email, hashed_password="x", full_name=email))
        await s.flush()
        s.add(Project(id=PROJECT, name=str(PROJECT), owner_id=OWNER, currency="USD"))
        await s.commit()
        yield s


async def _assembly(session):
    from app.modules.assemblies.schemas import AssemblyCreate, ComponentCreate
    from app.modules.assemblies.service import AssemblyService

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="GYP-1", name="Gypsum partition", unit="m2", currency="USD"),
        owner_id=str(OWNER),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Gypsum board", resource_type="material", factor=1.0, quantity=2.1, unit="m2", unit_cost="4"
        ),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Drywall installer", resource_type="labor", factor=1.0, quantity=0.35, unit="h", unit_cost="60"
        ),
    )
    return asm


async def _position(session, *, unit="m2", resources=None, unit_rate=25.0):
    from app.modules.boq.models import BOQ
    from app.modules.boq.schemas import PositionCreate
    from app.modules.boq.service import BOQService

    boq = BOQ(project_id=PROJECT, name="Partitions")
    session.add(boq)
    await session.flush()
    meta = {"resources": resources} if resources else {}
    return await BOQService(session).add_position(
        PositionCreate(
            boq_id=boq.id,
            ordinal="01.001",
            description="Interior partition",
            unit=unit,
            quantity=120,
            unit_rate=unit_rate,
            metadata=meta,
        )
    )


def _req(position_id, **kw):
    from app.modules.assemblies.schemas import ApplyToPositionRequest

    return ApplyToPositionRequest(position_id=position_id, **kw)


async def _reload(session, position_id):
    from app.modules.boq.repository import PositionRepository

    session.expire_all()
    return await PositionRepository(session).get_by_id(position_id)


@pytest.mark.asyncio
async def test_preview_shows_rate_and_writes_nothing(session):
    from app.modules.assemblies.service import AssemblyService

    asm = await _assembly(session)
    pos = await _position(session)

    out = await AssemblyService(session).apply_to_position(asm.id, _req(pos.id, dry_run=True))

    assert Decimal(out["before"]["unit_rate"]) == Decimal("25")
    assert Decimal(out["after"]["unit_rate"]) == Decimal("29.40")
    assert Decimal(out["after"]["total"]) == Decimal("3528.00")
    assert [r["name"] for r in out["resources"]] == ["Gypsum board", "Drywall installer"]
    assert out["warnings"] == []
    again = await _reload(session, pos.id)
    assert Decimal(str(again.unit_rate)) == Decimal("25")
    assert not (again.metadata_ or {}).get("resources")


@pytest.mark.asyncio
async def test_replace_sets_rate_resources_and_keeps_text(session):
    from app.modules.assemblies.service import AssemblyService

    asm = await _assembly(session)
    pos = await _position(session)

    out = await AssemblyService(session).apply_to_position(asm.id, _req(pos.id))

    saved = await _reload(session, pos.id)
    assert Decimal(str(saved.unit_rate)) == Decimal("29.40")
    assert Decimal(str(saved.total)) == Decimal("3528.00")
    assert saved.description == "Interior partition"
    assert saved.unit == "m2"
    rows = saved.metadata_["resources"]
    assert len(rows) == 2
    assert {r["assembly_code"] for r in rows} == {"GYP-1"}
    assert saved.metadata_["applied_assembly"]["code"] == "GYP-1"
    assert Decimal(out["previous"]["unit_rate"]) == Decimal("25")
    assert out["previous"]["metadata"] == {}


@pytest.mark.asyncio
async def test_factor_scales_every_component(session):
    from app.modules.assemblies.service import AssemblyService

    asm = await _assembly(session)
    pos = await _position(session)

    out = await AssemblyService(session).apply_to_position(asm.id, _req(pos.id, factor=1.1, dry_run=True))

    assert Decimal(out["after"]["unit_rate"]) == Decimal("32.34")
    board = next(r for r in out["resources"] if r["name"] == "Gypsum board")
    assert Decimal(str(board["quantity"])).quantize(Decimal("0.001")) == Decimal("2.310")


@pytest.mark.asyncio
async def test_append_keeps_existing_resources(session):
    from app.modules.assemblies.service import AssemblyService

    paint = {"name": "Paint", "type": "material", "unit": "m2", "quantity": 1, "unit_rate": 3, "total": 3}
    asm = await _assembly(session)
    pos = await _position(session, resources=[paint], unit_rate=3.0)

    await AssemblyService(session).apply_to_position(asm.id, _req(pos.id, mode="append"))

    saved = await _reload(session, pos.id)
    assert [r["name"] for r in saved.metadata_["resources"]] == ["Paint", "Gypsum board", "Drywall installer"]
    assert Decimal(str(saved.unit_rate)) == Decimal("32.40")


@pytest.mark.asyncio
async def test_unit_mismatch_is_a_warning_not_a_refusal(session):
    from app.modules.assemblies.service import AssemblyService

    asm = await _assembly(session)
    pos = await _position(session, unit="ft2")

    out = await AssemblyService(session).apply_to_position(asm.id, _req(pos.id, dry_run=True))

    assert out["warnings"] == [{"code": "unit_mismatch", "assembly_unit": "m2", "position_unit": "ft2"}]


@pytest.mark.asyncio
async def test_locked_bill_refuses_apply_but_allows_preview(session):
    from app.modules.assemblies.service import AssemblyService
    from app.modules.boq.repository import BOQRepository

    asm = await _assembly(session)
    pos = await _position(session)
    boq = await BOQRepository(session).get_by_id(pos.boq_id)
    boq.is_locked = True
    await session.flush()
    svc = AssemblyService(session)

    preview = await svc.apply_to_position(asm.id, _req(pos.id, dry_run=True))
    assert Decimal(preview["after"]["unit_rate"]) == Decimal("29.40")
    with pytest.raises(HTTPException) as exc:
        await svc.apply_to_position(asm.id, _req(pos.id))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_missing_position_is_404(session):
    from app.modules.assemblies.service import AssemblyService

    asm = await _assembly(session)
    with pytest.raises(HTTPException) as exc:
        await AssemblyService(session).apply_to_position(asm.id, _req(uuid.uuid4(), dry_run=True))
    assert exc.value.status_code == 404


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_stranger_cannot_reach_the_bill(session):
    from app.modules.assemblies.router import _verify_target_boq_owner

    pos = await _position(session)
    with pytest.raises(HTTPException) as exc:
        await _verify_target_boq_owner(session, pos.boq_id, str(STRANGER), payload=None)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "kw",
    [{"factor": 0}, {"factor": -1}, {"factor": 10001}, {"factor": float("nan")}, {"mode": "merge"}],
)
def test_request_bounds(kw):
    with pytest.raises(ValidationError):
        _req(uuid.uuid4(), **kw)
