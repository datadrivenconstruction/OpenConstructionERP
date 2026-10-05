# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the BOQ probes read the bill exactly as ``BOQService`` wrote it.

The bill is the fixture course's depot bill, built through ``create_boq``,
``create_section``, ``add_position``, ``update_position`` and ``add_markup``.
Each probe is asserted on the value AND on its match state against the
fixture's expected figure, so a probe that read the right column in the wrong
unit (a fraction profit rate, a float-tailed markup amount) fails here.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.boq.schemas import BOQCreate, MarkupCreate, PositionCreate, PositionUpdate, SectionCreate
from app.modules.boq.service import BOQService
from app.modules.trainer.checker.matching import Expectation
from app.modules.trainer.checker.registry import run_probe

MONEY = {"kind": "money", "tolerance": Decimal("0.01"), "currency": "GBP"}


async def _bill(world, project_id: uuid.UUID, *, blockwork_rate: str = "0") -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    service = BOQService(world.session)
    boq = await service.create_boq(BOQCreate(project_id=project_id, name="Quillmere Depot main bill"))
    section = await service.create_section(boq.id, SectionCreate(ordinal="01", description="Building works"))
    ids = {"section": section.id}
    for ordinal, unit, qty, rate in (
        ("01.001", "m3", 42, "118.50"),
        ("01.002", "m2", 310, blockwork_rate),
        ("01.003", "m2", 180, "61.75"),
    ):
        position = await service.add_position(
            PositionCreate(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=ordinal,
                description=f"Position {ordinal}",
                unit=unit,
                quantity=qty,
                unit_rate=Decimal(rate),
            )
        )
        ids[ordinal] = position.id
    return boq.id, ids


async def _markups(world, boq_id: uuid.UUID, *, profit_apply_to: str = "direct_cost") -> None:
    service = BOQService(world.session)
    await service.add_markup(
        boq_id, MarkupCreate(name="Overheads", percentage=8.0, apply_to="direct_cost", sort_order=1)
    )
    await service.add_markup(
        boq_id, MarkupCreate(name="Profit", percentage=5.0, apply_to=profit_apply_to, sort_order=2)
    )


async def _probe(world, refs: dict, type_name: str, args: dict, expectation: Expectation):
    return await run_probe(world.session, {"type": type_name, "args": args}, world.ctx(refs), expectation)


async def test_direct_cost_reads_the_seeded_bill_and_then_the_priced_one(world) -> None:
    boq_id, ids = await _bill(world, world.project_id)
    refs = {"boq.main": boq_id}
    expected = Expectation(value=Decimal("30414.00"), **MONEY)
    args = {"boq_ref": "boq.main", "field": "direct_cost"}

    untouched = await _probe(world, refs, "boq.cost_breakdown", args, expected)
    assert (untouched.value, untouched.status) == (Decimal("16092.00"), "mismatch")

    await BOQService(world.session).update_position(ids["01.002"], PositionUpdate(unit_rate=Decimal("46.20")))
    priced = await _probe(world, refs, "boq.cost_breakdown", args, expected)
    assert (priced.value, priced.status, priced.unit) == (Decimal("30414.00"), "match", "money")

    rate = await _probe(
        world,
        refs,
        "boq.position",
        {"boq_ref": "boq.main", "ordinal": "01.002", "field": "unit_rate"},
        Expectation(value=Decimal("46.20"), kind="money", tolerance=Decimal("0.005"), currency="GBP"),
    )
    assert rate.status == "match" and rate.value == Decimal("46.20")

    section = await _probe(world, refs, "boq.section_total", {"boq_ref": "boq.main", "section_ordinal": "01"}, expected)
    assert (section.value, section.status) == (Decimal("30414.00"), "match")


async def test_markups_are_read_as_amounts_and_as_percent(world) -> None:
    boq_id, _ids = await _bill(world, world.project_id, blockwork_rate="46.20")
    await _markups(world, boq_id)
    refs = {"boq.main": boq_id}

    grand = await _probe(
        world,
        refs,
        "boq.cost_breakdown",
        {"boq_ref": "boq.main", "field": "grand_total"},
        Expectation(value=Decimal("34367.82"), **MONEY),
    )
    assert (grand.value, grand.status) == (Decimal("34367.82"), "match")

    overheads = await _probe(
        world,
        refs,
        "boq.cost_breakdown",
        {"boq_ref": "boq.main", "field": "markup_amount", "markup_name": "Overheads"},
        Expectation(value=Decimal("2433.12"), **MONEY),
    )
    assert (overheads.value, overheads.status) == (Decimal("2433.12"), "match")

    # The course states profit as the fraction 0.05; the ERP column is percent.
    profit = await _probe(
        world,
        refs,
        "boq.markup",
        {"boq_ref": "boq.main", "name": "Profit", "field": "percentage"},
        Expectation(value=Decimal("0.05"), kind="percent", tolerance=Decimal("0.0001"), unit="fraction"),
    )
    assert profit.status == "match" and profit.unit == "percent"
    assert profit.value == Decimal("5.0")

    apply_to = await _probe(
        world,
        refs,
        "boq.markup",
        {"boq_ref": "boq.main", "name": "profit", "field": "apply_to"},
        Expectation(value="direct_cost", kind="text"),
    )
    assert (apply_to.value, apply_to.status) == ("direct_cost", "match")


async def test_profit_compounded_on_overheads_is_a_mismatch(world) -> None:
    boq_id, _ids = await _bill(world, world.project_id, blockwork_rate="46.20")
    await _markups(world, boq_id, profit_apply_to="cumulative")
    grand = await _probe(
        world,
        {"boq.main": boq_id},
        "boq.cost_breakdown",
        {"boq_ref": "boq.main", "field": "grand_total"},
        Expectation(value=Decimal("34367.82"), **MONEY),
    )
    assert (grand.value, grand.status) == (Decimal("34489.48"), "mismatch")


async def test_a_markup_the_learner_has_not_added_is_missing_not_zero(world) -> None:
    boq_id, _ids = await _bill(world, world.project_id)
    result = await _probe(
        world,
        {"boq.main": boq_id},
        "boq.markup",
        {"boq_ref": "boq.main", "name": "Profit", "field": "percentage"},
        Expectation(value=Decimal("5"), kind="percent", tolerance=Decimal("0.01")),
    )
    assert (result.value, result.status, result.is_missing) == (None, "unknown", True)


async def test_two_markups_with_one_name_are_ambiguous(world) -> None:
    boq_id, _ids = await _bill(world, world.project_id)
    service = BOQService(world.session)
    await service.add_markup(boq_id, MarkupCreate(name="Profit", percentage=5.0))
    await service.add_markup(boq_id, MarkupCreate(name="Profit", percentage=6.0))
    result = await _probe(
        world,
        {"boq.main": boq_id},
        "boq.markup",
        {"boq_ref": "boq.main", "name": "Profit", "field": "percentage"},
        Expectation(value=Decimal("5"), kind="percent", tolerance=Decimal("0.01")),
    )
    assert result.status == "unknown" and (result.detail or "").startswith("ambiguous")
    assert not result.is_missing


async def test_a_ref_into_another_project_is_refused_not_read(world) -> None:
    foreign_boq, _ids = await _bill(world, world.other_project_id, blockwork_rate="46.20")
    result = await _probe(
        world,
        {"boq.main": foreign_boq},
        "boq.cost_breakdown",
        {"boq_ref": "boq.main", "field": "direct_cost"},
        Expectation(value=Decimal("30414.00"), **MONEY),
    )
    assert result.value is None and result.status == "unknown"
    assert (result.detail or "").startswith("ref_outside_project")
    assert not result.is_missing


async def test_a_ref_the_seeder_never_wrote_is_missing(world) -> None:
    result = await _probe(
        world,
        {},
        "boq.cost_breakdown",
        {"boq_ref": "boq.main", "field": "direct_cost"},
        Expectation(value=Decimal("30414.00"), **MONEY),
    )
    assert result.status == "unknown" and result.is_missing
