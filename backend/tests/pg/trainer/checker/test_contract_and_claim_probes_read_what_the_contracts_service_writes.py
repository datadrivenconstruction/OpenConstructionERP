# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: ``contract.field``, ``claim.field`` and ``claim.line`` read what ``ContractsService`` wrote.

The contract is the fixture course's depot contract: four SOV lines summing to
34,502.82, retention 5 %, e-invoice VAT 20 %. Claim 1 values C01 at 100 % and
C02 at 50 % through ``auto_generate_claim_lines``, the same path the claim
screen's "generate from completion" uses: gross 12,138.00, retention 606.90,
net 11,531.10.
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
from app.modules.trainer.checker.matching import Expectation
from app.modules.trainer.checker.registry import run_probe

MONEY = {"kind": "money", "tolerance": Decimal("0.01"), "currency": "GBP"}
SOV = (("C01", "4977.00"), ("C02", "14322.00"), ("C03", "11250.00"), ("C04", "3953.82"))


async def _contract(world, project_id: uuid.UUID, *, metadata: dict[str, Any] | None = None) -> Any:
    service = ContractsService(world.session)
    contract = await service.create_contract(
        ContractCreate(
            code=f"QD-{uuid.uuid4().hex[:6]}",
            title="Quillmere Depot building contract",
            contract_type="lump_sum",
            project_id=project_id,
            start_date="2026-10-01",
            total_value=Decimal("34502.82"),
            currency="GBP",
            retention_percent=Decimal("5"),
            status="draft",
            metadata=metadata if metadata is not None else {"einvoice": {"vat_rate": 20}},
        ),
        user_id=str(world.user_id),
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
    return contract, lines


async def _claim(world, contract_id: uuid.UUID, lines: dict[str, uuid.UUID], completion: dict[str, str]) -> Any:
    service = ContractsService(world.session)
    claim = await service.create_progress_claim(
        ProgressClaimCreate(
            contract_id=contract_id, period_start="2026-10-01", period_end="2026-10-31", claim_date="2026-10-31"
        )
    )
    return await service.auto_generate_claim_lines(
        claim.id,
        AutoGenerateClaimRequest(completion={str(lines[c]): Decimal(p) for c, p in completion.items()}),
    )


async def _probe(world, refs: dict, type_name: str, args: dict, expectation: Expectation):
    return await run_probe(world.session, {"type": type_name, "args": args}, world.ctx(refs), expectation)


# ── contract.field ───────────────────────────────────────────────────────────


async def test_contract_fields_read_the_seeded_contract(world) -> None:
    contract, _lines = await _contract(world, world.project_id)
    refs = {"contract.main": contract.id}

    async def field(name: str, expectation: Expectation):
        return await _probe(
            world, refs, "contract.field", {"contract_ref": "contract.main", "field": name}, expectation
        )

    total = await field("total_value", Expectation(value=Decimal("34502.82"), **MONEY))
    assert (total.value, total.status) == (Decimal("34502.8200"), "match")

    # The course writes 5 % as {value: 5, unit: percent}; a fraction 0.05 must match too.
    retention = await field(
        "retention_percent",
        Expectation(value=Decimal("0.05"), kind="percent", tolerance=Decimal("0.0001"), unit="fraction"),
    )
    assert (retention.value, retention.status, retention.unit) == (Decimal("5.00"), "match", "percent")

    vat = await field("einvoice_vat_rate", Expectation(value=Decimal("20"), kind="percent", tolerance=Decimal("0.01")))
    assert (vat.value, vat.status) == (Decimal(20), "match")

    status = await field("status", Expectation(value="draft", kind="text"))
    assert (status.value, status.status) == ("draft", "match")

    # A draft contract has no frozen original value yet: missing, not 0.
    original = await field("original_contract_value", Expectation(value=Decimal("34502.82"), **MONEY))
    assert (original.value, original.status, original.is_missing) == (None, "unknown", True)


async def test_an_einvoice_vat_rate_written_as_an_object_is_unknown_never_zero(world) -> None:
    contract, _lines = await _contract(world, world.project_id, metadata={"einvoice": {"vat_rate": {"value": 20}}})
    vat = await _probe(
        world,
        {"contract.main": contract.id},
        "contract.field",
        {"contract_ref": "contract.main", "field": "einvoice_vat_rate"},
        Expectation(value=Decimal("0"), kind="percent", tolerance=Decimal("0.01")),
    )
    # Finance would charge 0 on it silently; the checker must not agree.
    assert (vat.value, vat.status) == (None, "unknown")
    assert (vat.detail or "").startswith("unreadable") and not vat.is_missing


async def test_an_absent_einvoice_vat_rate_reads_as_the_zero_finance_charges(world) -> None:
    contract, _lines = await _contract(world, world.project_id, metadata={})
    vat = await _probe(
        world,
        {"contract.main": contract.id},
        "contract.field",
        {"contract_ref": "contract.main", "field": "einvoice_vat_rate"},
        Expectation(value=Decimal("20"), kind="percent", tolerance=Decimal("0.01")),
    )
    assert (vat.value, vat.status) == (Decimal(0), "mismatch")


async def test_a_contract_in_another_project_is_refused(world) -> None:
    foreign, _lines = await _contract(world, world.other_project_id)
    result = await _probe(
        world,
        {"contract.main": foreign.id},
        "contract.field",
        {"contract_ref": "contract.main", "field": "total_value"},
        Expectation(value=Decimal("34502.82"), **MONEY),
    )
    assert result.value is None and (result.detail or "").startswith("ref_outside_project")


# ── claim.field / claim.line ─────────────────────────────────────────────────


async def test_the_latest_claim_is_read_and_a_selector_reads_pc_n(world) -> None:
    contract, lines = await _contract(world, world.project_id)
    refs = {"contract.main": contract.id}
    first = await _claim(world, contract.id, lines, {"C01": "100", "C02": "50"})
    assert first.claim_number == "PC-0001"

    async def claim(selector: object, name: str, expectation: Expectation):
        args = {"contract_ref": "contract.main", "claim_selector": selector, "field": name}
        return await _probe(world, refs, "claim.field", args, expectation)

    gross = await claim("latest", "gross_amount", Expectation(value=Decimal("12138.00"), **MONEY))
    retention = await claim("latest", "retention_amount", Expectation(value=Decimal("606.90"), **MONEY))
    net = await claim("latest", "net_due", Expectation(value=Decimal("11531.10"), **MONEY))
    assert [r.status for r in (gross, retention, net)] == ["match", "match", "match"]
    assert gross.value == Decimal("12138.00")

    status = await claim(1, "status", Expectation(value="draft", kind="text"))
    assert status.status == "match"

    # A second claim moves "latest"; selector 1 still reads PC-0001.
    second = await _claim(world, contract.id, lines, {"C01": "100", "C02": "100"})
    assert second.claim_number == "PC-0002"
    latest = await claim("latest", "gross_amount", Expectation(value=Decimal("12138.00"), **MONEY))
    assert latest.status == "mismatch" and latest.value != Decimal("12138.00")
    pinned = await claim(1, "gross_amount", Expectation(value=Decimal("12138.00"), **MONEY))
    assert pinned.status == "match"
    absent = await claim(3, "gross_amount", Expectation(value=Decimal("1"), **MONEY))
    assert absent.status == "unknown" and absent.is_missing


async def test_a_claim_line_is_read_by_its_sov_code(world) -> None:
    contract, lines = await _contract(world, world.project_id)
    await _claim(world, contract.id, lines, {"C01": "100", "C02": "50"})
    line = await _probe(
        world,
        {"contract.main": contract.id},
        "claim.line",
        {
            "contract_ref": "contract.main",
            "claim_selector": "latest",
            "line_code": "C02",
            "field": "period_completed_value",
        },
        Expectation(value=Decimal("7161.00"), **MONEY),
    )
    assert (line.value, line.status) == (Decimal("7161.0000"), "match")


async def test_no_claim_yet_is_missing(world) -> None:
    contract, _lines = await _contract(world, world.project_id)
    result = await _probe(
        world,
        {"contract.main": contract.id},
        "claim.field",
        {"contract_ref": "contract.main", "claim_selector": "latest", "field": "gross_amount"},
        Expectation(value=Decimal("12138.00"), **MONEY),
    )
    assert result.status == "unknown" and result.is_missing


async def test_the_last_lien_waiver_attached_to_the_claim_is_read(world) -> None:
    contract, lines = await _contract(world, world.project_id)
    claim = await _claim(world, contract.id, lines, {"C01": "100", "C02": "50"})
    service = ContractsService(world.session)

    async def waiver(name: str, expectation: Expectation):
        args = {"contract_ref": "contract.main", "claim_selector": "latest", "field": name}
        return await _probe(world, {"contract.main": contract.id}, "claim.lien_waiver", args, expectation)

    none_yet = await waiver("amount", Expectation(value=Decimal("11531.10"), **MONEY))
    assert none_yet.is_missing

    await service.transition_claim(claim.id, "submitted", actor_id=str(world.user_id))
    for amount, kind in (("100.00", "conditional_partial"), ("11531.10", "unconditional_partial")):
        await service.attach_lien_waiver(
            claim.id,
            {"waiver_type": kind, "through_date": "2026-10-31", "amount": amount, "signed_by": "Site agent"},
            actor_id=str(world.user_id),
        )
    amount = await waiver("amount", Expectation(value=Decimal("11531.10"), **MONEY))
    assert (amount.value, amount.status) == (Decimal("11531.10"), "match")
    kind = await waiver("waiver_type", Expectation(value="unconditional_partial", kind="text"))
    assert (kind.value, kind.status) == ("unconditional_partial", "match")
    through = await waiver("through_date", Expectation(value="2026-10-31", kind="date"))
    assert (through.value, through.status) == ("2026-10-31", "match")
