# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: ``variation.request`` and ``variation.order`` read what ``VariationsService`` wrote.

The fixture course's rooflight variation, 790.00 net, goes request -> submitted
-> approved -> ``convert_vr_to_vo`` against the seeded contract, the promotion
the variations screen performs. A selector counts orders on the seeded contract
in creation order, not order codes. The order is left ``issued``: completing it
publishes ``variations.contract_sum.updated``, whose subscriber opens its own
session, and the contract sum is not what these probes read.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.contracts.schemas import ContractCreate
from app.modules.contracts.service import ContractsService
from app.modules.trainer.checker.matching import Expectation
from app.modules.trainer.checker.registry import run_probe
from app.modules.variations.schemas import VariationOrderCreate, VariationRequestCreate
from app.modules.variations.service import VariationsService

MONEY = {"kind": "money", "tolerance": Decimal("0.01"), "currency": "GBP"}


async def _contract(world) -> uuid.UUID:
    contract = await ContractsService(world.session).create_contract(
        ContractCreate(
            code=f"QD-{uuid.uuid4().hex[:6]}",
            contract_type="lump_sum",
            project_id=world.project_id,
            total_value=Decimal("34502.82"),
            currency="GBP",
        ),
        user_id=str(world.user_id),
    )
    return contract.id


async def _promoted(world, contract_id: uuid.UUID | None, amount: str, title: str) -> tuple[uuid.UUID, uuid.UUID]:
    service = VariationsService(world.session)
    request = await service.create_request(
        VariationRequestCreate(
            project_id=world.project_id, title=title, estimated_cost_impact=Decimal(amount), currency="GBP"
        )
    )
    await service.transition_variation_request(request.id, "submitted", user_id=str(world.user_id))
    await service.transition_variation_request(request.id, "approved", user_id=str(world.user_id))
    order = await service.convert_vr_to_vo(
        request.id,
        VariationOrderCreate(
            project_id=world.project_id,
            title=title,
            final_cost_impact=Decimal(amount),
            currency="GBP",
            affected_contract_id=contract_id,
        ),
    )
    return request.id, order.id


async def _probe(world, refs: dict, type_name: str, args: dict, expectation: Expectation):
    return await run_probe(world.session, {"type": type_name, "args": args}, world.ctx(refs), expectation)


async def test_the_order_on_the_seeded_contract_is_read_and_others_are_not(world) -> None:
    contract_id = await _contract(world)
    refs = {"contract.main": contract_id}
    none_yet = await _probe(
        world,
        refs,
        "variation.order",
        {"contract_ref": "contract.main", "variation_ref": "latest", "field": "final_cost_impact"},
        Expectation(value=Decimal("790.00"), **MONEY),
    )
    assert none_yet.is_missing

    # An order on no contract is not this contract's variation. Created first,
    # it takes VO-0001, so "1" below can only mean "the first on this contract".
    await _promoted(world, None, "5000.00", "Unrelated works")
    await _promoted(world, contract_id, "790.00", "Rooflights")

    final = await _probe(
        world,
        refs,
        "variation.order",
        {"contract_ref": "contract.main", "variation_ref": "latest", "field": "final_cost_impact"},
        Expectation(value=Decimal("790.00"), **MONEY),
    )
    assert (final.value, final.status) == (Decimal("790.00"), "match")
    status = await _probe(
        world,
        refs,
        "variation.order",
        {"contract_ref": "contract.main", "variation_ref": 1, "field": "status"},
        Expectation(value="issued", kind="text"),
    )
    assert (status.value, status.status) == ("issued", "match")
    rooflights = await _probe(
        world,
        refs,
        "variation.order",
        {"contract_ref": "contract.main", "variation_ref": 1, "field": "final_cost_impact"},
        Expectation(value=Decimal("790.00"), **MONEY),
    )
    assert (rooflights.value, rooflights.status) == (Decimal("790.00"), "match")
    second = await _probe(
        world,
        refs,
        "variation.order",
        {"contract_ref": "contract.main", "variation_ref": 2, "field": "status"},
        Expectation(value="issued", kind="text"),
    )
    assert second.is_missing


async def test_the_request_selector_counts_requests_in_creation_order(world) -> None:
    contract_id = await _contract(world)
    await _promoted(world, contract_id, "790.00", "Rooflights")
    service = VariationsService(world.session)
    await service.create_request(
        VariationRequestCreate(project_id=world.project_id, title="Later", estimated_cost_impact=Decimal("10"))
    )

    first = await _probe(
        world,
        {},
        "variation.request",
        {"variation_ref": 1, "field": "agreed_cost_impact"},
        Expectation(value=Decimal("790.00"), **MONEY),
    )
    assert (first.value, first.status) == (Decimal("790.00"), "match")
    latest = await _probe(
        world,
        {},
        "variation.request",
        {"variation_ref": "latest", "field": "agreed_cost_impact"},
        Expectation(value=Decimal("790.00"), **MONEY),
    )
    # The later request is still a draft: nothing agreed yet is missing, not 0.
    assert latest.value is None and latest.is_missing
