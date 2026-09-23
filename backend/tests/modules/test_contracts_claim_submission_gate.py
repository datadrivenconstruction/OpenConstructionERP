# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submitting a progress claim runs the ``pay_application`` rules first.

The rules themselves are held red and green in
``tests/unit/test_contracts_pay_application_rules.py``. This file holds the
wiring: the service stamps the period dates on every write, the validation
route and the submit gate read the same report, an error keeps the claim in
draft with the finding in the refusal, and a rule set that checks nothing
refuses instead of passing.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.validation.engine import rule_registry
from app.modules.contracts import claim_context
from app.modules.contracts.models import Contract, ContractLine, ProgressClaimLine
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import PAY_APPLICATION_RULE_SET, register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"claim-gate-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(s) -> tuple[Contract, ContractLine]:
    project = Project(id=uuid.uuid4(), name="Claim gate", owner_id=OWNER_ID, currency="USD", country_code="US")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency="USD",
        total_value=Decimal("10000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    s.add(contract)
    await s.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="03 30 00",
        description="Cast-in-place concrete",
        quantity=Decimal("1"),
        unit_rate=Decimal("10000"),
        total_value=Decimal("10000"),
    )
    s.add(line)
    await s.flush()
    return contract, line


def _payload(contract_id: uuid.UUID, number: str, start: str, end: str) -> SimpleNamespace:
    return SimpleNamespace(
        contract_id=contract_id,
        claim_number=number,
        period_start=start,
        period_end=end,
        claim_date=end,
        currency="USD",
        metadata={},
    )


async def test_creating_and_editing_a_claim_keeps_its_dates_in_step(session) -> None:
    svc = ContractsService(session)
    contract, _line = await _contract(session)
    claim = await svc.create_progress_claim(_payload(contract.id, "PC-1", "2026-03-01", "2026-03-31"))
    assert (claim.period_from, claim.period_to, claim.application_date) == (
        date(2026, 3, 1),
        date(2026, 3, 31),
        date(2026, 3, 31),
    )

    await svc.update_progress_claim_fields(claim, {"period_end": "2026-04-02"})
    assert claim.period_to == date(2026, 4, 2)
    # Clearing the string clears the date rather than leaving the old day.
    await svc.update_progress_claim_fields(claim, {"period_end": ""})
    assert claim.period_to is None
    # A write that does not touch the period leaves the dates alone.
    await svc.update_progress_claim_fields(claim, {"claim_number": "PC-1A"})
    assert claim.period_from == date(2026, 3, 1)


async def test_the_report_names_the_previous_claim_in_period_order(session) -> None:
    svc = ContractsService(session)
    contract, _line = await _contract(session)
    # Created out of order on purpose: "previous" is by period, not by insert.
    april = await svc.create_progress_claim(_payload(contract.id, "PC-2", "2026-03-28", "2026-04-30"))
    await svc.create_progress_claim(_payload(contract.id, "PC-1", "2026-03-01", "2026-03-31"))

    report = await svc.validate_claim(april.id)
    assert report["unsupported_rule_sets"] == []
    assert report["errors"] == []
    overlap = [w for w in report["warnings"] if w["rule_id"] == "pay_application.period_overlap"]
    assert len(overlap) == 1
    assert overlap[0]["details"]["previous"] == "PC-1"


async def test_a_blocking_finding_keeps_the_claim_in_draft(session) -> None:
    svc = ContractsService(session)
    contract, line = await _contract(session)
    claim = await svc.create_progress_claim(_payload(contract.id, "PC-1", "2026-03-31", "2026-03-01"))
    session.add(
        ProgressClaimLine(
            id=uuid.uuid4(),
            progress_claim_id=claim.id,
            contract_line_id=line.id,
            period_completed_value=Decimal("12000"),
            cumulative_completed_value=Decimal("12000"),
        )
    )
    await session.flush()

    with pytest.raises(HTTPException) as refused:
        await svc.transition_claim(claim.id, "submitted")
    assert refused.value.status_code == 422
    assert "PC-1" in str(refused.value.detail)
    # The refusal is a toast, so it has to say how to get out of it, not
    # only what is wrong.
    assert "run Populate from progress again" in str(refused.value.detail)
    await session.refresh(claim)
    assert claim.status == "draft"

    report = await svc.validate_claim(claim.id)
    assert {e["rule_id"] for e in report["errors"]} >= {
        "pay_application.period_order",
        "pay_application.line_overbilled",
    }


async def test_a_clean_claim_submits(session) -> None:
    svc = ContractsService(session)
    contract, _line = await _contract(session)
    claim = await svc.create_progress_claim(_payload(contract.id, "PC-1", "2026-03-01", "2026-03-31"))
    submitted = await svc.transition_claim(claim.id, "submitted")
    assert submitted.status == "submitted"


async def test_a_rule_set_with_no_rules_refuses_rather_than_passes(session, monkeypatch) -> None:
    svc = ContractsService(session)
    contract, _line = await _contract(session)
    claim = await svc.create_progress_claim(_payload(contract.id, "PC-1", "2026-03-01", "2026-03-31"))

    monkeypatch.setitem(rule_registry._rule_sets, PAY_APPLICATION_RULE_SET, [])
    with pytest.raises(HTTPException) as refused:
        await svc.transition_claim(claim.id, "submitted")
    assert refused.value.status_code == 503
    await session.refresh(claim)
    assert claim.status == "draft"


async def test_with_no_other_module_registered_the_claim_is_checked_and_submits(session, monkeypatch) -> None:
    # The install without the subcontractors module: nothing registered.
    monkeypatch.setattr(claim_context, "_providers", {})
    svc = ContractsService(session)
    contract, _line = await _contract(session)
    claim = await svc.create_progress_claim(_payload(contract.id, "PC-1", "2026-03-01", "2026-03-31"))

    context = await svc.claim_rule_context(claim)
    assert set(context) == {
        "claim",
        "previous_claim",
        "lines",
        "percent_regressed",
        "currency",
        "as_of",
        "retention",
        # The claim's own stored money against what it should be, and what
        # it puts against a not-to-exceed cap. Both are read by rules that
        # block, so a provider may not replace either.
        "totals",
        "cap",
        # The ceiling on retention, which is a second thing entirely from the
        # not-to-exceed cap above it: one bounds what the job may bill, the
        # other bounds what may be withheld from what it bills.
        "retention_cap",
    }
    submitted = await svc.transition_claim(claim.id, "submitted")
    assert submitted.status == "submitted"


async def test_a_registered_provider_reaches_the_rule_context(session, monkeypatch) -> None:
    monkeypatch.setattr(claim_context, "_providers", {})
    seen: list[uuid.UUID] = []

    async def rollup(s, claim):
        seen.append(claim.id)
        return {"pay_apps": []}

    claim_context.register_claim_context_provider("subcontract_rollup", rollup)
    svc = ContractsService(session)
    contract, _line = await _contract(session)
    claim = await svc.create_progress_claim(_payload(contract.id, "PC-1", "2026-03-01", "2026-03-31"))

    context = await svc.claim_rule_context(claim)
    assert context["subcontract_rollup"] == {"pay_apps": []}
    assert seen == [claim.id]


async def test_a_provider_may_not_replace_what_the_core_rules_read(session, monkeypatch) -> None:
    monkeypatch.setattr(claim_context, "_providers", {})
    claim_context.register_claim_context_provider("lines", lambda s, claim: [])
    svc = ContractsService(session)
    contract, _line = await _contract(session)
    claim = await svc.create_progress_claim(_payload(contract.id, "PC-1", "2026-03-01", "2026-03-31"))

    with pytest.raises(RuntimeError, match="lines"):
        await svc.claim_rule_context(claim)
