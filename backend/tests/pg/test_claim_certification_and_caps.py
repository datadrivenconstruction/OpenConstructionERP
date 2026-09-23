# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a claim reads, what it freezes and what it is allowed to undo.

Four things a money review found, each one a place where a figure moved after
somebody had already acted on it:

* the progress bridge read the latest measurement on site rather than the one
  that belongs in the period being billed, so a claim raised for March and
  populated in May billed May's percent complete;
* a certified cost-plus or T&M claim stored nothing about what it certified,
  because there is no schedule of values for the retention engine to work on,
  so lines 4, 5 and 6 were rebuilt from today's world every time the sheet was
  drawn and the next claim's line 7 with them;
* a certified claim could be rejected back to draft, which reverses no money
  and leaves the invoice where it is;
* the not-to-exceed cap was checked when a T&M claim was worked out and never
  again, so two drafts that each fit alone both went out over it.

G702 line 8 is the claim's net due in every scenario that draws a certificate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.boq.models import BOQ, Position
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import BOQ_POSITION_META_KEY, ContractsService
from app.modules.contracts.validators import (
    PAY_APPLICATION_RULE_SET,
    register_contracts_validation_rules,
)
from app.modules.progress.models import ProgressEntry
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"cert-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project(session, *, country: str = "US") -> Project:
    project = Project(id=uuid.uuid4(), name="Works", owner_id=OWNER_ID, currency="USD", country_code=country)
    session.add(project)
    await session.flush()
    return project


async def _contract(session, project: Project, *, contract_type: str = "lump_sum", terms: dict | None = None):
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type=contract_type,
        currency="USD",
        total_value=Decimal("100000"),
        original_contract_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status="active",
        terms=terms or {},
    )
    session.add(contract)
    await session.flush()
    return contract


async def _line(session, contract, code: str, value: str, *, position_id: uuid.UUID | None = None) -> ContractLine:
    meta: dict = {}
    if position_id is not None:
        meta[BOQ_POSITION_META_KEY] = str(position_id)
    # The lump-sum generator prices a line at quantity x rate, not at the
    # stored total, so the three have to agree or the claim bills nothing.
    quantity = Decimal("10")
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code=code,
        description=f"Line {code}",
        quantity=quantity,
        unit_rate=Decimal(value) / quantity,
        total_value=Decimal(value),
        metadata_=meta,
    )
    session.add(line)
    await session.flush()
    return line


async def _claim(session, contract, number: str, month: int | None) -> ProgressClaim:
    dates: dict = {}
    if month is not None:
        dates = {
            "period_start": f"2026-{month:02d}-01",
            "period_end": f"2026-{month:02d}-28",
            "period_from": date(2026, month, 1),
            "period_to": date(2026, month, 28),
        }
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=number,
        currency="USD",
        status="draft",
        **dates,
    )
    session.add(claim)
    await session.flush()
    return claim


async def _certificate(svc: ContractsService, claim: ProgressClaim) -> dict:
    """The claim's application, asserting line 8 is what the claim is owed."""
    application = await svc.build_aia_application(claim.id)
    summary = application["summary"]
    assert summary["current_payment_due"] == Decimal(str(claim.net_due))
    assert summary["total_earned_less_retainage"] == summary["total_completed_stored"] - summary["retainage"]
    return application


async def _validate(svc: ContractsService, claim_id: uuid.UUID) -> dict:
    """The claim's report, having proved the rules behind it ran.

    An unregistered rule set is not an error. The engine logs it, lists it
    under ``unsupported_rule_sets`` and serialises a report with no findings
    in it, so every assertion of the shape ``errors == []`` passes whether
    the rules ran or not, and a set that silently stopped registering would
    read as a clean bill of health. This says out loud that the set is
    there, so these tests fail when it is not.
    """
    report = await svc.validate_claim(claim_id)
    assert PAY_APPLICATION_RULE_SET in report["rule_sets"]
    assert report["unsupported_rule_sets"] == []
    return report


async def test_the_bridge_reads_the_site_as_it_stood_at_the_period_end(session) -> None:
    project = await _project(session)
    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Main BOQ")
    session.add(boq)
    await session.flush()
    position = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="01.001",
        description="Concrete",
        unit="m3",
        quantity="100",
        unit_rate="100",
        total="10000",
    )
    session.add(position)
    await session.flush()
    contract = await _contract(session, project)
    await _line(session, contract, "A", "10000", position_id=position.id)
    claim = await _claim(session, contract, "PC-1", 3)

    for pct, recorded in (
        ("30", datetime(2026, 3, 10, 9, 0, tzinfo=UTC)),
        # The last reading taken inside the period, late on its closing day.
        # An as-of built from the bare date would drop this one.
        ("45", datetime(2026, 3, 28, 18, 30, tzinfo=UTC)),
        # April's work. It belongs on April's claim, not on this one.
        ("70", datetime(2026, 4, 14, 9, 0, tzinfo=UTC)),
    ):
        session.add(
            ProgressEntry(
                id=uuid.uuid4(),
                project_id=project.id,
                boq_position_id=position.id,
                period_label="2026-03",
                percent_complete=Decimal(pct),
                recorded_at=recorded,
            )
        )
    await session.flush()

    svc = ContractsService(session)
    preview = await svc.populate_claim_from_progress(claim.id)
    [item] = preview["items"]
    assert item["observed_pct"] == Decimal("45.0000")
    assert item["period_completed_value"] == Decimal("4500.0000")
    assert item["recorded_at"] == datetime(2026, 3, 28, 18, 30, tzinfo=UTC)

    # A claim with no period still reads the latest there is: there is no
    # period to read as of, and refusing to populate it would be worse.
    undated = await _claim(session, contract, "PC-2", None)
    [latest] = (await svc.populate_claim_from_progress(undated.id))["items"]
    assert latest["observed_pct"] == Decimal("70.0000")


async def test_certifying_a_claim_freezes_what_the_certificate_said(session) -> None:
    project = await _project(session)
    contract = await _contract(session, project)
    a = await _line(session, contract, "A", "60000")
    b = await _line(session, contract, "B", "40000")
    svc = ContractsService(session)

    march = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-1", 3)).id,
        AutoGenerateClaimRequest(completion={str(a.id): Decimal("40"), str(b.id): Decimal("40")}),
    )
    certificate = (await _certificate(svc, march))["summary"]
    assert certificate["total_completed_stored"] == Decimal("40000.00")
    assert certificate["retainage"] == Decimal("4000.00")
    # A claim generated against a schedule of values already carries lines 4
    # and 5: the retention engine writes them, and they are the figures the
    # certificate prints. Certification leaves them exactly as they are.
    assert (march.completed_stored_to_date, march.retention_held_to_date) == (
        Decimal("40000.0000"),
        Decimal("4000.0000"),
    )
    for target in ("submitted", "approved", "certified"):
        march = await svc.transition_claim(march.id, target, actor_id=str(OWNER_ID))
    assert (march.completed_stored_to_date, march.retention_held_to_date) == (
        Decimal("40000.0000"),
        Decimal("4000.0000"),
    )

    # Line 7 of the next claim is that claim's line 6 read off what it
    # certified, rather than rebuilt by summing what the earlier claims
    # happen to store today.
    april = await _claim(session, contract, "PC-2", 4)
    amount, basis = await svc.previous_certificates(april)
    assert (amount, basis) == (Decimal("36000.0000"), "snapshot")
    april = await svc.auto_generate_claim_lines(
        april.id, AutoGenerateClaimRequest(completion={str(a.id): Decimal("60"), str(b.id): Decimal("60")})
    )
    assert april.prior_claims_total == Decimal("36000")
    await _certificate(svc, april)


async def test_certifying_a_cost_plus_claim_freezes_what_the_certificate_said(session) -> None:
    # Cost-plus and T&M bill actual cost, so there is no schedule of values
    # behind the claim and the retention engine has nothing to work on. These
    # claims stored no certificate at all, and lines 4, 5 and 6 were rebuilt
    # from the claims around them every time the sheet was drawn.
    project = await _project(session)
    contract = await _contract(session, project, contract_type="cost_plus")
    svc = ContractsService(session)
    march = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-1", 3)).id,
        SimpleNamespace(actual_costs_total=Decimal("20000")),
    )
    assert (march.gross_amount, march.retention_amount) == (Decimal("20000"), Decimal("2000.0000"))
    assert (march.completed_stored_to_date, march.retention_held_to_date) == (None, None)
    certificate = (await _certificate(svc, march))["summary"]
    assert (certificate["total_completed_stored"], certificate["retainage"]) == (
        Decimal("20000.00"),
        Decimal("2000.00"),
    )

    for target in ("submitted", "approved", "certified"):
        march = await svc.transition_claim(march.id, target, actor_id=str(OWNER_ID))
    assert (march.completed_stored_to_date, march.retention_held_to_date) == (
        Decimal("20000.00"),
        Decimal("2000.00"),
    )
    # Re-rendered after certification, the certificate says what it said.
    assert (await _certificate(svc, march))["summary"]["total_earned_less_retainage"] == Decimal("18000.00")

    # Reconstructed rather than snapshot, and the amount is the same either
    # way here. March billed from cost and has no claim lines, so the
    # cumulative frozen on it is assembled from a schedule that has nothing
    # on it, and previous_certificates declines that basis. The two agree
    # while March is the only prior claim, because a lineless month freezes
    # the whole job anyway. They separate as soon as a month with lines sits
    # between: that month freezes the schedule alone and the snapshot then
    # loses March permanently.
    april = await _claim(session, contract, "PC-2", 4)
    assert await svc.previous_certificates(april) == (Decimal("18000.0000"), "reconstructed")


async def test_a_cost_plus_claim_outside_the_aia_countries_still_certifies(session) -> None:
    # The figures frozen at certification are facts about the contract, not
    # about the American form that prints them, so reading them back off the
    # payment application made certifying fail with the 404 that application
    # raises for a project outside the US, Canada and Australia. A German
    # cost-plus job holds retention exactly as an American one does.
    project = await _project(session, country="DE")
    contract = await _contract(session, project, contract_type="cost_plus")
    svc = ContractsService(session)
    march = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-1", 3)).id,
        SimpleNamespace(actual_costs_total=Decimal("20000")),
    )
    for target in ("submitted", "approved", "certified"):
        march = await svc.transition_claim(march.id, target, actor_id=str(OWNER_ID))
    assert march.status == "certified"
    assert (march.completed_stored_to_date, march.retention_held_to_date) == (
        Decimal("20000.00"),
        Decimal("2000.00"),
    )
    # The same figures an American project would have frozen, and the same
    # ones the next claim reads as previously certified. Reconstructed for
    # the reason given on the test above: March has no claim lines, so the
    # cumulative frozen on it is not a basis line 7 can trust.
    april = await _claim(session, contract, "PC-2", 4)
    assert await svc.previous_certificates(april) == (Decimal("18000.0000"), "reconstructed")

    # The form itself is still American only: nothing here opened it up.
    with pytest.raises(HTTPException) as refused:
        await svc.build_aia_application(march.id)
    assert refused.value.status_code == 404


async def test_a_certified_claim_cannot_be_rejected_back_into_draft(session) -> None:
    project = await _project(session)
    contract = await _contract(session, project)
    a = await _line(session, contract, "A", "60000")
    svc = ContractsService(session)
    march = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-1", 3)).id,
        AutoGenerateClaimRequest(completion={str(a.id): Decimal("40")}),
    )
    for target in ("submitted", "approved", "certified"):
        march = await svc.transition_claim(march.id, target, actor_id=str(OWNER_ID))

    # Certification raises the invoice. Rejecting reversed none of it, and
    # the claim then went back to draft to have its lines rewritten under
    # every later claim that had already read them.
    with pytest.raises(HTTPException) as refused:
        await svc.transition_claim(march.id, "rejected")
    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "certified_claim_not_reversible"
    assert march.status == "certified"

    # The refusal the editor gets says the same thing, rather than sending
    # the reader to a Reject button that the server then holds shut.
    with pytest.raises(HTTPException) as editable:
        await svc.populate_claim_from_progress(march.id)
    assert editable.value.status_code == 422
    assert "credit the invoice" in editable.value.detail["message"]

    # An approved claim is still rejectable: nothing has been certified.
    april = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-2", 4)).id,
        AutoGenerateClaimRequest(completion={str(a.id): Decimal("60")}),
    )
    april = await svc.transition_claim(april.id, "submitted")
    april = await svc.transition_claim(april.id, "approved")
    april = await svc.transition_claim(april.id, "rejected")
    assert april.status == "rejected"


async def test_two_time_and_materials_drafts_cannot_both_go_out_over_the_cap(session) -> None:
    project = await _project(session)
    contract = await _contract(session, project, contract_type="tm", terms={"tm_nte_cap": "50000"})
    svc = ContractsService(session)

    # Each draft fits under the cap on its own, which is all the generator
    # could ever see, and neither counts the other.
    first = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-1", 3)).id,
        SimpleNamespace(time_entries_total=Decimal("30000"), material_entries_total=Decimal("0")),
    )
    second = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-2", 4)).id,
        SimpleNamespace(time_entries_total=Decimal("30000"), material_entries_total=Decimal("0")),
    )
    assert (first.gross_amount, second.gross_amount) == (Decimal("30000"), Decimal("30000"))
    assert (await _validate(svc, second.id))["errors"] == []

    # The first goes out. The second now bills 60,000 against a 50,000 cap,
    # and the check that used to run only at generation never saw it.
    first = await svc.transition_claim(first.id, "submitted")
    report = await _validate(svc, second.id)
    [finding] = [f for f in report["errors"] if f["rule_id"] == "pay_application.within_nte_cap"]
    assert finding["severity"] == "error"
    with pytest.raises(HTTPException) as refused:
        await svc.transition_claim(second.id, "submitted")
    assert refused.value.status_code == 422

    # A claim that already went out is history: the cap is not re-litigated
    # on it, only on the draft that has not left yet.
    assert [f for f in (await _validate(svc, first.id))["errors"] if f["rule_id"].endswith("within_nte_cap")] == []
