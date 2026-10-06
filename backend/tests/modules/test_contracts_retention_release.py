# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Retention accrues on claims by policy and goes back through releases billed on a claim.

What was wrong before: a release was an entry appended to the contract's
metadata, counted as paid the moment it was written, with no documents behind
it and no claim to bill it on, so G702 line 5 never went down and the money
never reached a payment application. The release default was the old
planner's 50/50/100 of "the original" applied to what was still held, and
the contract, the API and the pack each named the events differently.

These tests walk one US contract (100,000 over two SoV lines of 60,000 and
40,000) through the ledger on PostgreSQL: the pack sizes the release, the
certificate of substantial completion gates it, billing it on the next claim
takes line 5 down and pays it, and column I adds up to line 5 on every
application.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import (
    Contract,
    ContractDocument,
    ContractLine,
    ProgressClaim,
    RetentionSchedule,
)
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import PREVIOUS_CERTIFICATES_SNAPSHOT, ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
TIERS_10_TO_5 = [{"from_percent_complete": "0", "rate": "10"}, {"from_percent_complete": "50", "rate": "5"}]


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"ret-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


@pytest_asyncio.fixture
async def world(session):
    project = Project(id=uuid.uuid4(), name="Retention", owner_id=OWNER_ID, currency="USD", country_code="US")
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    lines = []
    for index, (code, value) in enumerate([("A", "60000"), ("B", "40000")]):
        line = ContractLine(
            id=uuid.uuid4(),
            contract_id=contract.id,
            code=code,
            description=f"Line {code}",
            quantity=Decimal("1"),
            unit_rate=Decimal(value),
            total_value=Decimal(value),
            order_index=index,
        )
        session.add(line)
        lines.append(line)
    await session.flush()
    return SimpleNamespace(project=project, contract=contract, a=lines[0], b=lines[1])


async def _claim(session, world, number: str, month: int) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=world.contract.id,
        claim_number=number,
        period_start=f"2026-{month:02d}-01",
        period_end=f"2026-{month:02d}-28",
        period_from=date(2026, month, 1),
        period_to=date(2026, month, 28),
        currency="USD",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    return claim


async def _generate(svc: ContractsService, world, claim: ProgressClaim, a: str, b: str) -> ProgressClaim:
    request = AutoGenerateClaimRequest(completion={str(world.a.id): Decimal(a), str(world.b.id): Decimal(b)})
    return await svc.auto_generate_claim_lines(claim.id, request)


async def _approve(svc: ContractsService, claim: ProgressClaim) -> None:
    await svc.claim_repo.update_fields(claim.id, status="approved")


def _request(event: str, **extra):
    return SimpleNamespace(
        event=event,
        amount=extra.get("amount"),
        open_items_value=extra.get("open_items_value"),
        document_ids=extra.get("document_ids", []),
        released_on=None,
        notes=None,
    )


async def _foots(svc: ContractsService, claim: ProgressClaim) -> dict:
    """The application for ``claim``, asserting line 5 is column I added up."""
    application = await svc.build_aia_application(claim.id)
    column_i = sum((Decimal(str(line["retainage"])) for line in application["lines"]), Decimal("0"))
    assert application["summary"]["retainage"] == column_i
    split = application["summary"]["retainage_completed_work"] + application["summary"]["retainage_stored_materials"]
    assert split == application["summary"]["retainage"]
    return application


async def test_punch_withholding_stays_with_its_contract_and_never_guesses_legacy_links(session, world) -> None:
    svc = ContractsService(session)
    january = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50")
    await _approve(svc, january)
    other = Contract(
        project_id=world.project.id, code="OTHER", title="Other contractor", status="active", currency="USD"
    )
    session.add(other)
    await session.flush()
    for contract_id, cost in ((world.contract.id, "1000"), (other.id, "9000"), (None, "50000")):
        session.add(
            PunchItem(
                project_id=world.project.id,
                contract_id=contract_id,
                title="Outstanding work",
                status="open",
                rework_cost=cost,
                rework_cost_currency="USD",
            )
        )
    await session.flush()
    preview = await svc.preview_retention_release(world.contract.id, _request("practical_completion"))
    assert preview["open_items_count"] == 1
    assert preview["withheld_for_open_items"] == Decimal("1500.00")
    assert preview["amount"] == Decimal("3500.00")
    other_items = await svc._open_items(other)
    assert (other_items["count"], other_items["value"]) == (1, Decimal("9000"))


async def test_a_billed_release_takes_line_5_down_and_is_paid_with_the_claim(session, world) -> None:
    svc = ContractsService(session)
    january = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50")
    assert (january.gross_amount, january.retention_amount, january.net_due) == (
        Decimal("50000"),
        Decimal("5000"),
        Decimal("45000.0000"),
    )
    assert (january.completed_stored_to_date, january.retention_held_to_date) == (Decimal("50000"), Decimal("5000"))
    await _approve(svc, january)

    # One open punch item estimated at 1,000: the US pack holds back 1.5 times it.
    session.add(
        PunchItem(
            project_id=world.project.id,
            contract_id=world.contract.id,
            title="Door closer",
            status="open",
            rework_cost="1000",
            rework_cost_currency="USD",
        )
    )
    await session.flush()

    preview = await svc.preview_retention_release(world.contract.id, _request("practical_completion"))
    assert preview["event"] == "substantial_completion"
    assert preview["rule_source"] == "regional_pack"
    assert (preview["held"], preview["percent_of_held"]) == (Decimal("5000.00"), Decimal("100"))
    assert (preview["open_items_count"], preview["withheld_for_open_items"]) == (1, Decimal("1500.00"))
    assert (preview["amount"], preview["remaining"]) == (Decimal("3500.00"), Decimal("1500.00"))
    assert preview["required_documents"] == ["certificate_substantial_completion"]

    release = await svc.create_retention_release(world.contract.id, _request("substantial_completion"), "qs")
    assert (release.status, release.amount) == ("proposed", Decimal("3500.00"))

    # Not without the certificate.
    with pytest.raises(HTTPException) as refused:
        await svc.approve_retention_release(release.id, SimpleNamespace(document_ids=[]), "pm")
    assert refused.value.status_code == 422
    assert [f["rule_id"] for f in refused.value.detail["errors"]] == ["retention_release.documents_attached"]

    certificate = ContractDocument(
        contract_id=world.contract.id, doc_role="certificate_substantial_completion", title="CSC signed"
    )
    session.add(certificate)
    await session.flush()
    release = await svc.approve_retention_release(release.id, SimpleNamespace(document_ids=[certificate.id]), "pm")
    assert release.status == "approved"

    february = await _generate(svc, world, await _claim(session, world, "PC-2", 2), "50", "50")
    assert february.retention_held_to_date == Decimal("5000")
    release = await svc.bill_retention_release(release.id, SimpleNamespace(progress_claim_id=february.id), "qs")
    await session.refresh(february)
    assert release.status == "billed"
    # Line 5 went down by the release, and line 8 pays it.
    assert february.retention_held_to_date == Decimal("1500")
    assert february.net_due == Decimal("3500.0000")

    application = await _foots(svc, february)
    summary = application["summary"]
    assert summary["retainage"] == Decimal("1500.00")
    assert summary["previous_certificates_total"] == Decimal("45000.00")
    assert summary["previous_certificates_basis"] == PREVIOUS_CERTIFICATES_SNAPSHOT
    assert summary["current_payment_due"] == Decimal("3500.00")

    # Voided while February is still a draft, it comes off again.
    await svc.void_retention_release(release.id, "qs")
    await session.refresh(february)
    assert (february.retention_held_to_date, february.net_due) == (Decimal("5000"), Decimal("0.0000"))
    await _foots(svc, february)


async def test_paid_back_retention_leaves_the_checklist_and_the_dashboard(session, world) -> None:
    svc = ContractsService(session)
    january = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50")
    await _approve(svc, january)
    release = await svc.create_retention_release(
        world.contract.id, _request("rate_step_down", amount=Decimal("2000")), "qs"
    )
    release = await svc.approve_retention_release(release.id, SimpleNamespace(document_ids=[]), "pm")
    february = await _generate(svc, world, await _claim(session, world, "PC-2", 2), "60", "60")
    await svc.bill_retention_release(release.id, SimpleNamespace(progress_claim_id=february.id), "qs")

    # Billed on a draft: committed, not yet paid back.
    summary = await svc.retention_summary(world.contract)
    assert (summary["released"], summary["pending_release"]) == (Decimal("0"), Decimal("2000.00"))

    await _approve(svc, february)
    summary = await svc.retention_summary(world.contract)
    # January 5,000 plus February's 1,000 accrued; 2,000 went back.
    assert (summary["accrued"], summary["released"], summary["held"]) == (
        Decimal("6000.0000"),
        Decimal("2000.00"),
        Decimal("4000.0000"),
    )
    dashboard = await svc.contract_dashboard(world.contract.id)
    assert Decimal(str(dashboard["retention_held"])) == Decimal("4000.0000")
    checklist = await svc.final_account_checklist(world.contract.id)
    [item] = [i for i in checklist["items"] if i["key"] == "retention_released"]
    assert Decimal(item["based_on"]["retention_outstanding"]) == Decimal("4000")


async def test_a_completion_event_is_released_once_under_any_of_its_names(session, world) -> None:
    svc = ContractsService(session)
    january = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50")
    await _approve(svc, january)
    await svc.create_retention_release(world.contract.id, _request("substantial_completion", amount=1000), "qs")
    for name in ("substantial_completion", "practical_completion", "handover"):
        with pytest.raises(HTTPException) as refused:
            await svc.create_retention_release(world.contract.id, _request(name, amount=1000), "qs")
        assert refused.value.status_code == 409
        assert refused.value.detail["error"] == "retention_event_already_released"


async def test_a_release_logged_the_old_way_still_counts(session, world) -> None:
    svc = ContractsService(session)
    january = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50")
    await _approve(svc, january)
    await svc.contract_repo.update_fields(
        world.contract.id,
        metadata_={"retention_releases": [{"event": "practical_completion", "amount_released": "2500"}]},
    )
    with pytest.raises(HTTPException) as refused:
        await svc.create_retention_release(world.contract.id, _request("substantial_completion"), "qs")
    assert refused.value.status_code == 409
    # And its money is gone from what the final completion can release.
    preview = await svc.preview_retention_release(world.contract.id, _request("final_completion"))
    assert preview["held"] == Decimal("2500.00")


async def test_nothing_held_is_nothing_to_release(session, world) -> None:
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as refused:
        await svc.create_retention_release(world.contract.id, _request("final_completion"), "qs")
    assert refused.value.status_code == 422
    assert refused.value.detail["error"] == "nothing_to_release"


async def test_an_event_without_a_percentage_needs_an_amount(session, world) -> None:
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as refused:
        await svc.preview_retention_release(world.contract.id, _request("rate_step_down"))
    assert refused.value.detail["error"] == "release_amount_required"


async def test_the_older_endpoint_proposes_instead_of_paying(session, world) -> None:
    svc = ContractsService(session)
    january = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50")
    await _approve(svc, january)
    result = await svc.release_retention(world.contract.id, "punch_list_complete", actor_id="qs")
    # The old planner's name for final completion; the US pack releases all of it.
    assert (result["event"], result["status"]) == ("final_completion", "proposed")
    assert Decimal(result["amount_released"]) == Decimal("5000.00")
    assert (await svc.retention_summary(world.contract))["released"] == Decimal("0")


@pytest.mark.parametrize("value", ["-5", "150", "tomorrow"])
async def test_the_older_endpoint_refuses_a_schedule_it_cannot_apply(session, world, value) -> None:
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as refused:
        await svc.release_retention(
            world.contract.id, "substantial_completion", custom_schedule={"substantial_completion": value}
        )
    assert refused.value.status_code == 400


async def test_a_stepped_policy_retains_by_band_and_column_i_adds_up(session, world) -> None:
    svc = ContractsService(session)
    session.add(RetentionSchedule(contract_id=world.contract.id, accrual_rule={"tiers": TIERS_10_TO_5}))
    await session.flush()
    claim = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "60", "60")
    # 50,000 at 10% and 10,000 at 5%.
    assert (claim.retention_amount, claim.retention_held_to_date) == (Decimal("5500"), Decimal("5500"))
    lines = {ln.contract_line_id: ln for ln in await svc.claim_line_repo.list_for_claim(claim.id)}
    assert (lines[world.a.id].retention_to_date, lines[world.b.id].retention_to_date) == (
        Decimal("3300"),
        Decimal("2200"),
    )
    assert lines[world.a.id].retention_rate == Decimal("9.1667")
    application = await _foots(svc, claim)
    assert application["summary"]["retainage"] == Decimal("5500.00")


async def test_a_recompute_step_down_is_proposed_not_paid(session, world) -> None:
    svc = ContractsService(session)
    session.add(
        RetentionSchedule(
            contract_id=world.contract.id, accrual_rule={"tiers": TIERS_10_TO_5, "tier_mode": "recompute"}
        )
    )
    await session.flush()
    january = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "40", "40")
    assert january.retention_held_to_date == Decimal("4000")
    await _approve(svc, january)

    february = await _generate(svc, world, await _claim(session, world, "PC-2", 2), "60", "60")
    # 5% of 60,000 is 3,000; the 4,000 already held stays until a person releases the rest.
    assert (february.retention_amount, february.retention_held_to_date) == (Decimal("0"), Decimal("4000"))
    [proposal] = [r for r in await svc.release_repo.list_for_contract(world.contract.id) if r.status != "void"]
    assert (proposal.event, proposal.status, proposal.amount) == ("rate_step_down", "proposed", Decimal("1000.00"))
    assert proposal.metadata_["proposed_for_claim_id"] == str(february.id)

    # Back below the threshold, the proposal goes.
    await _generate(svc, world, february, "45", "45")
    assert [r.status for r in await svc.release_repo.list_for_contract(world.contract.id)] == ["void"]


async def test_a_claim_whose_policy_moved_is_held_back_until_worked_out_again(session, world) -> None:
    svc = ContractsService(session)
    claim = await _generate(svc, world, await _claim(session, world, "PC-1", 1), "60", "60")
    assert claim.retention_held_to_date == Decimal("6000")
    session.add(RetentionSchedule(contract_id=world.contract.id, accrual_rule={"tiers": TIERS_10_TO_5}))
    await session.flush()

    assert _stale(await svc.validate_claim(claim.id)) == 1

    claim = await svc.roll_claim_retention(claim.id)
    assert claim.retention_held_to_date == Decimal("5500")
    assert _stale(await svc.validate_claim(claim.id)) == 0


def _stale(report: dict) -> int:
    return sum(1 for f in report["errors"] if f["rule_id"] == "pay_application.retention_matches_policy")


# ── Through the endpoints ────────────────────────────────────────────────
#
# The tests above call the service. These call the router functions, because
# three things live only there: the request schema (which is what resolves an
# older event name), the tenancy check, and the response model.


async def test_the_endpoints_take_an_older_event_name_and_answer_with_the_canonical_one(session, world) -> None:
    from app.modules.contracts.router import (
        create_retention_release,
        preview_retention_release,
        retention_summary,
    )
    from app.modules.contracts.schemas import RetentionReleaseCreate, RetentionReleasePreviewRequest

    svc = ContractsService(session)
    await _approve(svc, await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50"))

    preview = await preview_retention_release(
        world.contract.id,
        RetentionReleasePreviewRequest(event="practical_completion"),
        session,
        str(OWNER_ID),
    )
    assert (preview.event, preview.amount) == ("substantial_completion", Decimal("5000.00"))
    assert preview.required_documents == ["certificate_substantial_completion"]

    row = await create_retention_release(
        world.contract.id,
        RetentionReleaseCreate(event="handover", amount=Decimal("1000")),
        session,
        str(OWNER_ID),
    )
    assert (row.event, row.status, row.amount) == ("substantial_completion", "proposed", Decimal("1000.00"))
    # The response carries the row's metadata under its own name.
    assert row.metadata["rule_source"] == "regional_pack"

    summary = await retention_summary(world.contract.id, session, str(OWNER_ID))
    assert (summary.held, summary.pending_release, summary.available_for_release) == (
        Decimal("5000.0000"),
        Decimal("1000.00"),
        Decimal("4000.0000"),
    )
    assert [r.id for r in summary.releases] == [row.id]


async def test_the_endpoints_walk_a_release_from_proposed_to_billed(session, world) -> None:
    from app.modules.contracts.router import (
        approve_retention_release,
        bill_retention_release,
        create_retention_release,
        recalculate_claim_retention,
    )
    from app.modules.contracts.schemas import (
        RetentionReleaseApprove,
        RetentionReleaseBill,
        RetentionReleaseCreate,
    )

    svc = ContractsService(session)
    await _approve(svc, await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50"))
    certificate = ContractDocument(
        contract_id=world.contract.id, doc_role="certificate_substantial_completion", title="CSC"
    )
    session.add(certificate)
    await session.flush()

    row = await create_retention_release(
        world.contract.id,
        RetentionReleaseCreate(event="substantial_completion", document_ids=[certificate.id]),
        session,
        str(OWNER_ID),
    )
    row = await approve_retention_release(row.id, RetentionReleaseApprove(), session, str(OWNER_ID))
    assert (row.status, row.document_ids) == ("approved", [str(certificate.id)])

    february = await _generate(svc, world, await _claim(session, world, "PC-2", 2), "50", "50")
    row = await bill_retention_release(
        row.id, RetentionReleaseBill(progress_claim_id=february.id), session, str(OWNER_ID)
    )
    assert (row.status, row.progress_claim_id) == ("billed", february.id)

    claim = await recalculate_claim_retention(february.id, session, str(OWNER_ID))
    assert (claim.retention_held_to_date, claim.net_due) == (Decimal("0.0000"), Decimal("5000.0000"))


async def test_a_release_on_a_contract_the_caller_cannot_see_is_not_found(session, world) -> None:
    from app.modules.contracts.router import retention_summary, void_retention_release

    svc = ContractsService(session)
    await _approve(svc, await _generate(svc, world, await _claim(session, world, "PC-1", 1), "50", "50"))
    row = await svc.create_retention_release(world.contract.id, _request("final_completion"), "qs")
    stranger = uuid.uuid4()

    for call in (
        retention_summary(world.contract.id, session, str(stranger)),
        void_retention_release(row.id, session, str(stranger)),
    ):
        with pytest.raises(HTTPException) as refused:
            await call
        # 404, not 403: the leak policy is that a contract you cannot see
        # does not exist.
        assert refused.value.status_code == 404


async def test_only_a_manager_may_approve_a_release() -> None:
    # Releasing money the owner is holding is not an estimator's call, and the
    # endpoint is the only place that says so.
    from app.core.permissions import Role, permission_registry
    from app.modules.contracts.permissions import register_contracts_permissions

    register_contracts_permissions()
    assert not permission_registry.role_has_permission(Role.VIEWER, "contracts.approve_retention_release")
    assert not permission_registry.role_has_permission(Role.EDITOR, "contracts.approve_retention_release")
    assert permission_registry.role_has_permission(Role.MANAGER, "contracts.approve_retention_release")
