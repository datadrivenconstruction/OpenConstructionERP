# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Edge cases of restructuring a bill and of pricing a recurring line once (issue 554).

Run:
    cd backend
    python -m pytest tests/modules/boq/test_restructure_edges_and_set_rate_guards.py -q
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ
from app.modules.boq.restructure import plan_restructure, to_position_fields, to_section_fields
from app.modules.boq.schemas import BulkPositionUpdate, PositionCreate, RestructureRequest
from app.modules.boq.service import MAX_NESTING_DEPTH, BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

IDS = [uuid.uuid4() for _ in range(12)]


# -- pure planner ------------------------------------------------------------


def test_plan_of_an_empty_list_is_empty() -> None:
    assert plan_restructure([], max_depth=8) == []


def test_plan_rejects_a_negative_level() -> None:
    with pytest.raises(ValueError, match="0 or more"):
        plan_restructure([(IDS[0], -1)], max_depth=8)


def test_plan_of_only_positions_leaves_them_at_the_root() -> None:
    plan = plan_restructure([(i, 0) for i in IDS[:4]], max_depth=8)
    assert all(p.parent_id is None and not p.is_section for p in plan)


def test_plan_nests_up_to_the_limit_and_refuses_one_more() -> None:
    rows = [(IDS[i], i + 1) for i in range(MAX_NESTING_DEPTH)]
    plan = plan_restructure(rows, max_depth=MAX_NESTING_DEPTH)
    assert plan[-1].parent_id == IDS[MAX_NESTING_DEPTH - 2]
    with pytest.raises(ValueError, match="deeper"):
        plan_restructure([*rows, (IDS[MAX_NESTING_DEPTH], MAX_NESTING_DEPTH + 1)], max_depth=MAX_NESTING_DEPTH)


def test_plan_returns_to_a_shallower_section_after_a_deep_one() -> None:
    plan = plan_restructure([(IDS[0], 1), (IDS[1], 2), (IDS[2], 3), (IDS[3], 2), (IDS[4], 0)], max_depth=8)
    assert [p.parent_id for p in plan] == [None, IDS[0], IDS[1], IDS[0], IDS[3]]


def test_plan_handles_a_large_bill() -> None:
    rows = [(uuid.uuid4(), 1 if i % 100 == 0 else 0) for i in range(20_000)]
    plan = plan_restructure(rows, max_depth=8)
    assert len(plan) == 20_000
    assert plan[150].parent_id == rows[100][0]
    assert plan[19_999].sort_order == 19_999


class _Row:
    def __init__(self, **kw) -> None:
        self.unit = kw.get("unit", "m3")
        self.quantity = kw.get("quantity", "2.625")
        self.unit_rate = kw.get("unit_rate", "120.005")
        self.total = kw.get("total", "315.013125")
        self.metadata_ = kw.get("metadata_", {"resources": [{"quantity": "1"}], "keep": 1})


def test_section_fields_keep_the_exact_decimal_strings_and_the_other_metadata() -> None:
    fields = to_section_fields(_Row())
    kept = fields["metadata_"]["converted_from_position"]
    assert (kept["quantity"], kept["unit_rate"], kept["total"]) == ("2.625", "120.005", "315.013125")
    assert "resources" not in fields["metadata_"] and fields["metadata_"]["keep"] == 1
    assert (fields["quantity"], fields["unit_rate"], fields["total"]) == ("0", "0", "0")


def test_position_fields_round_trip_restores_figures_and_resources() -> None:
    row = _Row()
    section = _Row(
        unit="section", quantity="0", unit_rate="0", total="0", metadata_=to_section_fields(row)["metadata_"]
    )
    back = to_position_fields(section)
    assert (back["unit"], back["quantity"], back["unit_rate"], back["total"]) == (
        "m3",
        "2.625",
        "120.005",
        "315.013125",
    )
    assert back["metadata_"]["resources"] == [{"quantity": "1"}]
    assert "converted_from_position" not in back["metadata_"]


def test_a_section_that_was_never_a_position_becomes_an_unpriced_lump_sum() -> None:
    back = to_position_fields(_Row(unit="section", quantity="0", unit_rate="0", total="0", metadata_=None))
    assert (back["unit"], back["quantity"], back["total"]) == ("lsum", "0", "0")


def test_a_damaged_conversion_record_does_not_break_the_conversion() -> None:
    back = to_position_fields(_Row(metadata_={"converted_from_position": {"unit": None, "quantity": None}}))
    assert back["unit"] == "lsum" and back["quantity"] == "0"


# -- request schemas -----------------------------------------------------------


def test_restructure_request_refuses_an_empty_bill_and_bad_levels() -> None:
    with pytest.raises(ValidationError):
        RestructureRequest(rows=[])
    with pytest.raises(ValidationError):
        RestructureRequest(rows=[{"position_id": IDS[0], "level": -1}])
    with pytest.raises(ValidationError):
        RestructureRequest(rows=[{"position_id": IDS[0], "level": 33}])
    with pytest.raises(ValidationError):
        RestructureRequest(rows=[{"position_id": "not-a-uuid", "level": 1}])


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("0.0001"), Decimal("1e12")])
def test_set_rate_accepts_the_edges(rate: Decimal) -> None:
    assert BulkPositionUpdate(ids=[IDS[0]], set_rate=rate).set_rate == rate


def test_set_rate_refuses_above_the_cap_and_mixing_with_updates() -> None:
    with pytest.raises(ValidationError):
        BulkPositionUpdate(ids=[IDS[0]], set_rate=Decimal("1.1e12"))
    with pytest.raises(ValidationError):
        BulkPositionUpdate(ids=[IDS[0]], set_rate=Decimal("1"), updates={"unit": "m"})
    with pytest.raises(ValidationError):
        BulkPositionUpdate(ids=[IDS[0]])


def test_set_rate_does_not_pass_through_a_float() -> None:
    assert BulkPositionUpdate(ids=[IDS[0]], set_rate="0.1").set_rate == Decimal("0.1")


# -- service -------------------------------------------------------------------


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _bill(session: AsyncSession, currency: str = "EUR", region: str = "FR", locked: bool = False):
    owner = User(email=f"edge-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="E", role="admin")
    session.add(owner)
    await session.flush()
    project = Project(name=f"Edge {uuid.uuid4().hex[:6]}", currency=currency, region=region, owner_id=owner.id)
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="DPGF", status="draft", metadata_={}, is_locked=locked)
    session.add(boq)
    await session.flush()
    return BOQService(session), boq.id


async def _add(svc: BOQService, boq_id, ordinal, desc, unit="m3", qty="1", rate="1"):
    return await svc.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal=ordinal,
            description=desc,
            unit=unit,
            quantity=Decimal(qty),
            unit_rate=Decimal(rate),
        )
    )


def _req(*pairs):
    return RestructureRequest(rows=[{"position_id": p.id, "level": lv} for p, lv in pairs])


def _sum_totals(*rows) -> Decimal:
    return sum((Decimal(r.total) for r in rows), Decimal("0"))


@pytest.mark.asyncio
async def test_restructure_of_a_bill_without_rows_is_refused(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    one = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await svc.restructure_positions(boq_id, RestructureRequest(rows=[{"position_id": one, "level": 1}]))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_restructure_refuses_a_row_of_another_bill_and_a_repeat(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    _, other_id = await _bill(session)
    mine = await _add(svc, boq_id, "1", "A")
    foreign = await _add(svc, other_id, "1", "B")
    with pytest.raises(HTTPException) as exc:
        await svc.restructure_positions(boq_id, _req((mine, 0), (foreign, 0)))
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc2:
        await svc.restructure_positions(boq_id, _req((mine, 0), (mine, 0)))
    assert exc2.value.status_code == 422
    assert foreign.parent_id is None


@pytest.mark.asyncio
async def test_totals_of_priced_lines_do_not_change_when_chapters_are_cut(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    chap = await _add(svc, boq_id, "1", "Gros oeuvre", "pcs", "1", "0")
    a = await _add(svc, boq_id, "1.1", "Béton", "m3", "2.625", "120.005")
    b = await _add(svc, boq_id, "1.2", "Acier", "kg", "0.001", "99999999.99")
    before = _sum_totals(a, b)
    snapshot = [(r.quantity, r.unit_rate, r.total) for r in (a, b)]
    await svc.restructure_positions(boq_id, _req((chap, 1), (a, 0), (b, 0)))
    assert _sum_totals(a, b) == before
    assert [(r.quantity, r.unit_rate, r.total) for r in (a, b)] == snapshot
    assert a.parent_id == chap.id and b.parent_id == chap.id


@pytest.mark.asyncio
async def test_a_priced_line_turned_into_a_section_leaves_the_sum_and_comes_back(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    line = await _add(svc, boq_id, "1", "Béton", "m3", "2.625", "120")
    figures = (line.unit, line.quantity, line.unit_rate, line.total)
    await svc.restructure_positions(boq_id, _req((line, 1)))
    assert Decimal(line.total) == 0
    await svc.restructure_positions(boq_id, _req((line, 0)))
    assert (line.unit, line.quantity, line.unit_rate, line.total) == figures


@pytest.mark.asyncio
async def test_resources_survive_the_round_trip(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    line = await _add(svc, boq_id, "1", "Béton", "m3", "2", "10")
    line.metadata_ = {"resources": [{"name": "Ciment", "quantity": "2", "unit_rate": "5"}]}
    await svc.restructure_positions(boq_id, _req((line, 2)))
    assert "resources" not in line.metadata_
    await svc.restructure_positions(boq_id, _req((line, 0)))
    assert line.metadata_["resources"][0]["name"] == "Ciment"


@pytest.mark.asyncio
async def test_nested_levels_and_converting_a_parent_back_reparents_its_children(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    c1 = await _add(svc, boq_id, "1", "C1", "pcs", "1", "0")
    c11 = await _add(svc, boq_id, "1.1", "C11", "pcs", "1", "0")
    leaf = await _add(svc, boq_id, "1.1.1", "Leaf", "m2", "3", "4")
    await svc.restructure_positions(boq_id, _req((c1, 1), (c11, 2), (leaf, 0)))
    assert leaf.parent_id == c11.id and c11.parent_id == c1.id
    await svc.restructure_positions(boq_id, _req((c1, 1), (c11, 0), (leaf, 0)))
    assert c11.unit == "pcs" and c11.parent_id == c1.id and leaf.parent_id == c1.id


@pytest.mark.asyncio
async def test_sort_order_follows_the_request_order(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    a = await _add(svc, boq_id, "1", "A")
    b = await _add(svc, boq_id, "2", "B")
    c = await _add(svc, boq_id, "3", "C")
    await svc.restructure_positions(boq_id, _req((c, 0), (a, 0), (b, 0)))
    assert (c.sort_order, a.sort_order, b.sort_order) == (0, 1, 2)


@pytest.mark.asyncio
async def test_a_linked_line_cannot_become_a_section(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    line = await _add(svc, boq_id, "1", "Béton")
    line.link_group_id = uuid.uuid4()
    line.link_role = "master"
    with pytest.raises(HTTPException) as exc:
        await svc.restructure_positions(boq_id, _req((line, 1)))
    assert exc.value.status_code == 422
    assert line.unit == "m3"


@pytest.mark.asyncio
async def test_a_locked_bill_refuses_restructure_and_set_rate(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session, locked=True)
    ghost = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await svc.restructure_positions(boq_id, RestructureRequest(rows=[{"position_id": ghost, "level": 0}]))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc2:
        await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[ghost], set_rate=Decimal("1")))
    assert exc2.value.status_code == 409


@pytest.mark.asyncio
async def test_restructure_works_in_another_currency_and_region(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session, currency="JPY", region="JP")
    a = await _add(svc, boq_id, "1", "A", "m", "1.5", "1234567")
    await svc.restructure_positions(boq_id, _req((a, 1)))
    await svc.restructure_positions(boq_id, _req((a, 0)))
    assert Decimal(a.total) == Decimal("1851850.5")


@pytest.mark.asyncio
async def test_a_large_bill_is_restructured_in_one_call(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    rows = [await _add(svc, boq_id, str(i), f"L{i}", "m", "1", "2") for i in range(1, 121)]
    levels = [(r, 1 if i % 20 == 0 else 0) for i, r in enumerate(rows)]
    res = await svc.restructure_positions(boq_id, _req(*levels))
    assert (res.sections, res.positions) == (6, 114)
    assert rows[25].parent_id == rows[20].id


# -- set_rate ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_rate_skips_sections_and_resource_priced_rows(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    plain = await _add(svc, boq_id, "1", "Béton", "m3", "3", "100")
    resourced = await _add(svc, boq_id, "2", "Béton", "m3", "3", "50")
    resourced.metadata_ = {"resources": [{"name": "x", "quantity": "1", "unit_rate": "50"}]}
    empty_res = await _add(svc, boq_id, "3", "Béton", "m3", "3", "60")
    empty_res.metadata_ = {"resources": [{"name": "x", "quantity": "0", "unit_rate": "50"}]}
    section = await _add(svc, boq_id, "4", "Lot", "section", "0", "0")
    res = await svc.bulk_update_positions(
        boq_id, BulkPositionUpdate(ids=[plain.id, resourced.id, empty_res.id, section.id], set_rate=Decimal("80"))
    )
    assert (res.updated, res.unchanged, res.skipped) == (2, 2, 0)
    assert Decimal(resourced.unit_rate) == Decimal("50")
    assert Decimal(empty_res.unit_rate) == Decimal("80") and Decimal(empty_res.total) == Decimal("240")
    assert Decimal(section.unit_rate) == 0 and Decimal(section.total) == 0


@pytest.mark.asyncio
async def test_set_rate_leaves_an_instance_whose_master_is_in_the_request(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    group = uuid.uuid4()
    master = await _add(svc, boq_id, "1", "Béton", "m3", "1", "10")
    inst = await _add(svc, boq_id, "2", "Béton", "m3", "1", "10")
    master.link_group_id = inst.link_group_id = group
    master.link_role, inst.link_role = "master", "instance"
    res = await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[master.id, inst.id], set_rate=Decimal("25")))
    assert res.updated == 1 and res.unchanged == 1
    assert Decimal(master.unit_rate) == Decimal("25")


@pytest.mark.asyncio
async def test_set_rate_prices_an_instance_whose_master_is_not_selected(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    group = uuid.uuid4()
    master = await _add(svc, boq_id, "1", "Béton", "m3", "1", "10")
    inst = await _add(svc, boq_id, "2", "Béton", "m3", "2", "10")
    master.link_group_id = inst.link_group_id = group
    master.link_role, inst.link_role = "master", "instance"
    res = await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[inst.id], set_rate=Decimal("25")))
    assert res.updated == 1
    assert Decimal(inst.total) == Decimal("50")


@pytest.mark.asyncio
async def test_set_rate_zero_is_a_real_rate_and_keeps_decimal_precision(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    a = await _add(svc, boq_id, "1", "Béton", "m3", "2.625", "10")
    await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[a.id], set_rate=Decimal("0")))
    assert Decimal(a.unit_rate) == 0 and Decimal(a.total) == 0
    await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[a.id], set_rate=Decimal("0.1")))
    assert Decimal(a.total) == Decimal("0.2625")
    await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[a.id], set_rate=Decimal("1e12")))
    assert Decimal(a.total) == Decimal("2625000000000")


@pytest.mark.asyncio
async def test_set_rate_with_the_same_rate_twice_changes_nothing_the_second_time(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    a = await _add(svc, boq_id, "1", "Béton", "m3", "1", "10")
    first = await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[a.id], set_rate=Decimal("12.50")))
    second = await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[a.id], set_rate=Decimal("12.5")))
    assert (first.updated, second.updated, second.unchanged) == (1, 0, 1)


@pytest.mark.asyncio
async def test_set_rate_on_an_unknown_or_foreign_row_is_not_applied(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    _, other = await _bill(session)
    foreign = await _add(svc, other, "1", "Béton", "m3", "1", "10")
    try:
        res = await svc.bulk_update_positions(boq_id, BulkPositionUpdate(ids=[foreign.id], set_rate=Decimal("99")))
    except HTTPException as exc:
        assert exc.status_code in (404, 422)
    else:
        assert res.updated == 0
    assert Decimal(foreign.unit_rate) == Decimal("10")
