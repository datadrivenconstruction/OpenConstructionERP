"""Changing one resource is previewed across the region, then applied as one audited step.

Worked example: cement ``CEM-1`` costs 100 on the sheet and goes to 120.

* W1 uses 0.3 of it (line 30.00) next to labour 50.00, rate 80.00:
  new line 36.00, delta +6.00, new rate 86.00.
* W2 uses 1.5 (line 150.00), rate 150.00: new line 180.00, delta +30.00.
* W3 does not use it and is not touched.
* W4 carries it on a line with no quantity: unreadable, reported, left alone.
* Assembly A1 uses W1 at factor 2: delta 2 x 6.00 = +12.00.

Work-item delta total is 36.00.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.costs.resource_impact import (
    ResourceChangeRefusedError,
    ResourceImpactService,
    rewrite_components,
)
from app.modules.costs.validators import check_resource_change
from tests._pg import transactional_session

REGION = "ZZ_IMPACT"


def _cem(qty: object, rate: float = 100.0, cost: float | None = None) -> dict:
    comp = {"code": "CEM-1", "name": "Cement CEM I", "type": "material", "unit": "t", "unit_rate": rate}
    if qty is not None:
        comp["quantity"] = qty
    if cost is not None:
        comp["cost"] = cost
    return comp


_LAB = {"code": "LAB-1", "name": "Mason", "type": "labor", "unit": "h", "quantity": 2, "unit_rate": 25, "cost": 50}


def test_rewrite_follows_the_worked_example() -> None:
    comps, delta, matched, unreadable = rewrite_components(
        [_cem(0.3, cost=30.0), dict(_LAB)], "CEM-1", Decimal("120"), None
    )
    assert (delta, matched, unreadable) == (Decimal("6.00"), 1, False)
    assert comps[0]["cost"] == 36.0
    assert comps[0]["unit_rate"] == 120.0
    assert comps[1] == _LAB


def test_a_line_without_quantity_makes_the_recipe_unreadable() -> None:
    _, _, matched, unreadable = rewrite_components([_cem(None)], "CEM-1", Decimal("120"), None)
    assert (matched, unreadable) == (1, True)


def test_renaming_a_codeless_resource_onto_another_is_blocked() -> None:
    issues = check_resource_change(
        old_name="sand",
        new_name="gravel",
        old_price=Decimal("5"),
        new_price=Decimal("5"),
        old_key="name:sand",
        new_key="name:gravel",
        existing_keys={"name:gravel"},
        unreadable_items=0,
    )
    assert [i.code for i in issues if i.blocking] == ["resource.change.key_collision"]


def test_no_change_is_blocked() -> None:
    issues = check_resource_change(
        old_name="a",
        new_name="a",
        old_price=Decimal("1"),
        new_price=Decimal("1"),
        old_key="K",
        new_key="K",
        existing_keys=set(),
        unreadable_items=0,
    )
    assert issues[0].code == "resource.change.nothing_to_change"


async def _seed(session) -> dict[str, uuid.UUID]:  # noqa: ANN001
    from app.modules.assemblies.models import Assembly, Component
    from app.modules.costs.models import CostItem, ResourcePrice

    session.add(
        ResourcePrice(
            region=REGION,
            resource_key="CEM-1",
            resource_code="CEM-1",
            resource_name="Cement CEM I",
            resource_type="material",
            unit="t",
            unit_price="100.00",
            currency="EUR",
            source="cwicr_import",
            is_active=True,
        )
    )
    ids: dict[str, uuid.UUID] = {}
    recipes = {
        "W1": ("80.00", [_cem(0.3, cost=30.0), dict(_LAB)]),
        "W2": ("150.00", [_cem(1.5, cost=150.0)]),
        "W3": ("50.00", [dict(_LAB)]),
        "W4": ("10.00", [_cem(None)]),
    }
    for code, (rate, comps) in recipes.items():
        item = CostItem(
            id=uuid.uuid4(),
            code=f"{code}-{uuid.uuid4().hex[:6]}",
            description=code,
            unit="m3",
            rate=rate,
            currency="EUR",
            source="cwicr",
            components=comps,
            region=REGION,
            is_active=True,
        )
        session.add(item)
        ids[code] = item.id
    asm = Assembly(id=uuid.uuid4(), code=f"A1-{uuid.uuid4().hex[:6]}", name="A1", unit="m3")
    session.add(asm)
    await session.flush()
    session.add(Component(assembly_id=asm.id, cost_item_id=ids["W1"], description="W1", factor="2", unit="m3"))
    await session.flush()
    ids["A1"] = asm.id
    return ids


@pytest.mark.asyncio
async def test_preview_counts_items_assemblies_and_deltas() -> None:
    async with transactional_session() as session:
        ids = await _seed(session)
        res = await ResourceImpactService(session).preview(REGION, "CEM-1", new_unit_price=Decimal("120"))
        by_id = {row["id"]: row for row in res.cost_items}
        assert res.cost_items_count == 2
        assert res.cost_items_unreadable == 1
        assert res.cost_items_delta_total == Decimal("36.00")
        assert by_id[ids["W1"]]["new_rate"] == Decimal("86.00")
        assert by_id[ids["W2"]]["delta"] == Decimal("30.00")
        assert ids["W3"] not in by_id
        assert res.assemblies_count == 1
        assert res.assemblies[0]["delta"] == Decimal("12.00")
        assert [i.code for i in res.issues] == ["resource.change.unreadable_lines"]


@pytest.mark.asyncio
async def test_apply_writes_rates_name_and_sheet_and_audits() -> None:
    from sqlalchemy import select

    from app.core.audit import AuditEntry
    from app.modules.costs.models import CostItem, ResourcePrice

    async with transactional_session() as session:
        ids = await _seed(session)
        svc = ResourceImpactService(session)
        with pytest.raises(ResourceChangeRefusedError):
            await svc.apply(REGION, "CEM-1", new_unit_price=Decimal("120"), expected_cost_items=5)
        res = await svc.apply(
            REGION, "CEM-1", new_unit_price=Decimal("120"), new_name="Cement CEM I 42.5", expected_cost_items=2
        )
        assert res.applied
        w1 = (await session.execute(select(CostItem).where(CostItem.id == ids["W1"]))).scalar_one()
        w4 = (await session.execute(select(CostItem).where(CostItem.id == ids["W4"]))).scalar_one()
        assert w1.rate == "86.00"
        assert w1.components[0]["name"] == "Cement CEM I 42.5"
        assert w4.rate == "10.00"
        row = (await session.execute(select(ResourcePrice).where(ResourcePrice.region == REGION))).scalar_one()
        assert (row.unit_price, row.resource_name, row.source) == ("120.00", "Cement CEM I 42.5", "user")
        audit = (await session.execute(select(AuditEntry).where(AuditEntry.id == res.audit_id))).scalar_one()
        assert audit.details["cost_items"] == 2
        assert audit.details["old_unit_price"] == "100.00"


@pytest.mark.asyncio
async def test_apply_refuses_a_truncated_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import select

    from app.modules.costs import resource_impact
    from app.modules.costs.models import CostItem, ResourcePrice

    monkeypatch.setattr(resource_impact, "_MAX_ITEMS", 1)
    monkeypatch.setattr(resource_impact, "_SCAN_ROWS", 1)
    async with transactional_session() as session:
        ids = await _seed(session)
        svc = ResourceImpactService(session)
        with pytest.raises(ResourceChangeRefusedError) as err:
            await svc.apply(REGION, "CEM-1", new_unit_price=Decimal("120"))
        assert err.value.code == "resource.change.truncated"
        row = (await session.execute(select(ResourcePrice).where(ResourcePrice.region == REGION))).scalar_one()
        assert row.unit_price == "100.00"
        w1 = (await session.execute(select(CostItem).where(CostItem.id == ids["W1"]))).scalar_one()
        assert w1.rate == "80.00"


@pytest.mark.asyncio
async def test_apply_refuses_when_the_sheet_price_moved_since_the_preview() -> None:
    async with transactional_session() as session:
        await _seed(session)
        svc = ResourceImpactService(session)
        for stale in ({"expected_old_unit_price": Decimal("95")}, {"expected_new_unit_price": Decimal("125")}):
            with pytest.raises(ResourceChangeRefusedError) as err:
                await svc.apply(REGION, "CEM-1", new_unit_price=Decimal("120"), expected_cost_items=2, **stale)
            assert err.value.code == "resource.change.stale_preview"
        res = await svc.apply(
            REGION,
            "CEM-1",
            new_unit_price=Decimal("120"),
            expected_cost_items=2,
            expected_old_unit_price=Decimal("100"),
            expected_new_unit_price=Decimal("120.00"),
        )
        assert res.applied


@pytest.mark.asyncio
async def test_bill_positions_of_inaccessible_projects_are_not_counted() -> None:
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    async with transactional_session(disable_fks=True) as session:
        await _seed(session)
        owner, stranger = uuid.uuid4(), str(uuid.uuid4())
        project = Project(id=uuid.uuid4(), name="P", owner_id=owner)
        boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="B")
        session.add_all([project, boq])
        await session.flush()
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq.id,
                ordinal="01",
                description="p",
                unit="m3",
                quantity="1",
                unit_rate="80.00",
                total="80.00",
                source="manual",
                metadata_={"resources": [_cem(0.3, cost=30.0)]},
            )
        )
        await session.flush()
        svc = ResourceImpactService(session)
        mine = await svc.preview(REGION, "CEM-1", new_unit_price=Decimal("120"), user_id=str(owner))
        theirs = await svc.preview(REGION, "CEM-1", new_unit_price=Decimal("120"), user_id=stranger)
        assert mine.boq_positions_count == 1
        assert theirs.boq_positions_count == 0
