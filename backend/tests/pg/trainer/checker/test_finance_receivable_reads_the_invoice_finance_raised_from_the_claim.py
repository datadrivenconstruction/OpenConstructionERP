# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: ``finance.receivable`` reads the invoice finance raised from a certified claim.

The claim goes draft -> submitted -> approved -> certified through
``ContractsService.transition_claim``. Certification's event is published for
after the commit, which this rolled-back test never reaches, so the test calls
``FinanceService.create_receivable_from_claim`` itself: the same call the
event handler makes.

Finance charges VAT as gross x ``metadata.einvoice.vat_rate`` percent. With a
rate of 20 the 12,138.00 claim carries 2,427.60 of tax. With the rate written
as an object finance reads it as 0 and charges nothing; the probe reports
that 0, because it is what the ledger holds.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.modules.contracts.schemas import (
    AutoGenerateClaimRequest,
    ContractCreate,
    ContractLineCreate,
    ProgressClaimCreate,
)
from app.modules.contracts.service import ContractsService
from app.modules.finance.service import FinanceService
from app.modules.trainer.checker.matching import Expectation
from app.modules.trainer.checker.registry import run_probe

MONEY = {"kind": "money", "tolerance": Decimal("0.01"), "currency": "GBP"}
SOV = (("C01", "4977.00"), ("C02", "14322.00"), ("C03", "11250.00"), ("C04", "3953.82"))


async def _certified_claim(world, metadata: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    service = ContractsService(world.session)
    user = str(world.user_id)
    contract = await service.create_contract(
        ContractCreate(
            code=f"QD-{uuid.uuid4().hex[:6]}",
            title="Quillmere Depot building contract",
            contract_type="lump_sum",
            project_id=world.project_id,
            start_date="2026-10-01",
            total_value=Decimal("34502.82"),
            currency="GBP",
            retention_percent=Decimal("5"),
            metadata=metadata,
        ),
        user_id=user,
    )
    lines = {}
    for i, (code, amount) in enumerate(SOV):
        line = await service.create_line(
            ContractLineCreate(
                contract_id=contract.id,
                code=code,
                description=f"Line {code}",
                unit="item",
                quantity=Decimal(1),
                unit_rate=Decimal(amount),
                order_index=i,
            )
        )
        lines[code] = line.id
    claim = await service.create_progress_claim(
        ProgressClaimCreate(
            contract_id=contract.id, period_start="2026-10-01", period_end="2026-10-31", claim_date="2026-10-31"
        )
    )
    await service.auto_generate_claim_lines(
        claim.id,
        AutoGenerateClaimRequest(completion={str(lines["C01"]): Decimal(100), str(lines["C02"]): Decimal(50)}),
    )
    for status in ("submitted", "approved", "certified"):
        await service.transition_claim(claim.id, status, actor_id=user)
    await FinanceService(world.session).create_receivable_from_claim(claim.id, actor_id=user)
    return contract.id, claim.id


async def _receivable(world, contract_id: uuid.UUID, field: str, expected: str):
    return await run_probe(
        world.session,
        {
            "type": "finance.receivable",
            "args": {"contract_ref": "contract.main", "claim_selector": "latest", "field": field},
        },
        world.ctx({"contract.main": contract_id}),
        Expectation(value=Decimal(expected), **MONEY),
    )


async def test_the_receivable_carries_vat_at_the_contracts_einvoice_rate(world) -> None:
    contract_id, _claim_id = await _certified_claim(world, {"einvoice": {"vat_rate": 20}})
    subtotal = await _receivable(world, contract_id, "amount_subtotal", "12138.00")
    tax = await _receivable(world, contract_id, "tax_amount", "2427.60")
    assert (subtotal.value, subtotal.status) == (Decimal("12138.00"), "match")
    assert (tax.value, tax.status) == (Decimal("2427.60"), "match")


async def test_a_vat_rate_written_as_an_object_leaves_the_invoice_untaxed(world) -> None:
    contract_id, _claim_id = await _certified_claim(world, {"einvoice": {"vat_rate": {"value": 20}}})
    tax = await _receivable(world, contract_id, "tax_amount", "2427.60")
    assert (tax.value, tax.status) == (Decimal(0), "mismatch")


async def test_no_receivable_before_certification_is_missing(world) -> None:
    service = ContractsService(world.session)
    contract = await service.create_contract(
        ContractCreate(
            code=f"QD-{uuid.uuid4().hex[:6]}",
            contract_type="lump_sum",
            project_id=world.project_id,
            total_value=Decimal("34502.82"),
            currency="GBP",
        ),
        user_id=str(world.user_id),
    )
    await service.create_progress_claim(
        ProgressClaimCreate(
            contract_id=contract.id, period_start="2026-10-01", period_end="2026-10-31", claim_date="2026-10-31"
        )
    )
    tax = await _receivable(world, contract.id, "tax_amount", "2427.60")
    assert tax.status == "unknown" and tax.is_missing
