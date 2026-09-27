# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rolling a subcontractor pay application into a GC progress claim, on PostgreSQL.

Including a pay application is the one write the rollup makes: it records that
a person chose to bill that sub's work on this claim. It never writes the
claim's lines; those still go through the contracts preview and commit. What
has to hold, and is pinned here against a real database because the include
path takes a row lock:

* a claim past editing refuses the change (409), in both directions;
* a pay application already in another claim is not taken from it (409);
* a pay application in another currency is refused (422) and, because the
  include is all-or-nothing, so is every other one in the same request;
* include then exclude leaves the pay application where it started, and the
  rollup shows it on the claim's line in between;
* submitting the claim runs the subcontract rules through the contracts
  module's rule set, so a missing waiver the agreement requires blocks;
* finance approval sets the amount approved on each line, which is what the
  rollup bills: a lowered amount reaches it, an amount above the claim or a
  line from elsewhere is refused with nothing written, and an approval that
  names no amounts approves every unset line as claimed;
* a lowered approval is also what gets paid: the approved gross, its retention
  and its net are recorded, the retention accrued follows them, and the paid
  event outside systems read carries the approved net, not the claimed one;
* a lien waiver filed against a pay application must be in its currency;
* the lines of a pay application answer with a page envelope whose total
  counts the pay application's lines rather than the rows on the page.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio


async def _world(
    session: Any,
    *,
    suffix: str,
    requires_lien_waiver: bool = False,
    pay_app_status: str = "finance_approved",
    line_approved: Decimal = Decimal("2000"),
) -> dict[str, Any]:
    """A project with one prime contract, one open claim and one sub pay application.

    By default the pay application is approved with its line approved as
    claimed; the finance approval tests start it one step earlier, with the
    line's approved amount unset, the way the portal submits it.
    """
    from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
    from app.modules.projects.models import Project
    from app.modules.subcontractors.models import (
        PaymentApplication,
        PaymentApplicationLine,
        SubcontractAgreement,
        Subcontractor,
        WorkPackage,
    )
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"sub-rollup-{suffix}@site.example",
        hashed_password="x",
        full_name="Project Accountant",
    )
    project = Project(id=uuid.uuid4(), name="Sub rollup probe", owner_id=owner.id, currency="USD")
    contract = Contract(
        id=uuid.uuid4(),
        project_id=project.id,
        code=f"PC-{suffix}",
        title="Prime contract",
        currency="USD",
        counterparty_type="client",
        status="active",
    )
    line = ContractLine(
        id=uuid.uuid4(), contract_id=contract.id, code="03.10", description="Footings", total_value=Decimal("10000")
    )
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-001",
        currency="USD",
        status="draft",
        period_start="2026-04-01",
        period_end="2026-04-30",
        period_from=date(2026, 4, 1),
        period_to=date(2026, 4, 30),
    )
    sub = Subcontractor(id=uuid.uuid4(), legal_name=f"Example Concrete {suffix}")
    agreement = SubcontractAgreement(
        id=uuid.uuid4(),
        subcontractor_id=sub.id,
        project_id=project.id,
        title="Concrete subcontract",
        currency="USD",
        total_value=Decimal("8000"),
        status="active",
        retention_percent=Decimal("10"),
        requires_lien_waiver=requires_lien_waiver,
    )
    package = WorkPackage(id=uuid.uuid4(), agreement_id=agreement.id, name="Footings", contract_line_id=line.id)
    pay_app = PaymentApplication(
        id=uuid.uuid4(),
        agreement_id=agreement.id,
        application_number="PA-1",
        status=pay_app_status,
        currency="USD",
        gross_amount=Decimal("2000"),
        retention_amount=Decimal("200"),
        net_amount=Decimal("1800"),
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    pa_line = PaymentApplicationLine(
        id=uuid.uuid4(),
        payment_application_id=pay_app.id,
        work_package_id=package.id,
        claimed_amount=Decimal("2000"),
        certified_amount=Decimal("2000"),
        approved_amount=line_approved,
    )
    session.add(owner)
    await session.flush()
    session.add(project)
    await session.flush()
    session.add_all([contract, sub])
    await session.flush()
    session.add_all([line, claim, agreement])
    await session.flush()
    session.add(package)
    await session.flush()
    session.add(pay_app)
    await session.flush()
    session.add(pa_line)
    await session.flush()
    return {
        "project": project,
        "contract": contract,
        "line": line,
        "claim": claim,
        "agreement": agreement,
        "package": package,
        "pay_app": pay_app,
        "pa_line": pa_line,
    }


async def _pay_app_claim(session: Any, pay_app_id: uuid.UUID) -> uuid.UUID | None:
    from sqlalchemy import select

    from app.modules.subcontractors.models import PaymentApplication

    return (
        await session.execute(select(PaymentApplication.progress_claim_id).where(PaymentApplication.id == pay_app_id))
    ).scalar_one()


async def test_include_and_exclude_round_trip_and_the_rollup_shows_it_in_between(pg_session) -> None:
    from app.modules.subcontractors.service import SubcontractorService

    world = await _world(pg_session, suffix=uuid.uuid4().hex[:8])
    service = SubcontractorService(pg_session)
    claim, pay_app, line = world["claim"], world["pay_app"], world["line"]

    before = await service.claim_rollup(claim.id)
    assert [c["payment_application_id"] for c in before["candidates"]] == [pay_app.id]
    assert before["included"] == []

    await service.include_payment_applications(claim.id, [pay_app.id])
    assert await _pay_app_claim(pg_session, pay_app.id) == claim.id
    # Including it twice is a no-op, not a conflict with itself.
    await service.include_payment_applications(claim.id, [pay_app.id])

    during = await service.claim_rollup(claim.id)
    assert [row["application_number"] for row in during["included"]] == ["PA-1"]
    [rolled] = during["lines"]
    assert rolled["contract_line_id"] == line.id
    assert rolled["sub_period_approved"] == Decimal("2000")
    assert during["candidates"] == []

    await service.exclude_payment_application(pay_app.id)
    assert await _pay_app_claim(pg_session, pay_app.id) is None
    after = await service.claim_rollup(claim.id)
    assert after["included"] == []


async def test_a_claim_past_editing_refuses_include_and_exclude(pg_session) -> None:
    from sqlalchemy import update

    from app.modules.contracts.models import ProgressClaim
    from app.modules.subcontractors.service import SubcontractorService

    world = await _world(pg_session, suffix=uuid.uuid4().hex[:8])
    service = SubcontractorService(pg_session)
    claim_id, pay_app_id = world["claim"].id, world["pay_app"].id
    await service.include_payment_applications(claim_id, [pay_app_id])

    # An ORM-enabled UPDATE, so the claim already in the session sees the new
    # status the way a later request reading it fresh would.
    await pg_session.execute(update(ProgressClaim).where(ProgressClaim.id == claim_id).values(status="approved"))

    with pytest.raises(HTTPException) as refused_exclude:
        await service.exclude_payment_application(pay_app_id)
    assert refused_exclude.value.status_code == 409
    assert refused_exclude.value.detail["code"] == "claim_not_editable"
    assert await _pay_app_claim(pg_session, pay_app_id) == claim_id

    with pytest.raises(HTTPException) as refused_include:
        await service.include_payment_applications(claim_id, [pay_app_id])
    assert refused_include.value.status_code == 409
    assert refused_include.value.detail["code"] == "claim_not_editable"


async def test_a_pay_application_in_another_claim_is_not_taken_from_it(pg_session) -> None:
    from app.modules.contracts.models import ProgressClaim
    from app.modules.subcontractors.service import SubcontractorService

    world = await _world(pg_session, suffix=uuid.uuid4().hex[:8])
    service = SubcontractorService(pg_session)
    claim, pay_app = world["claim"], world["pay_app"]
    other = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=world["contract"].id,
        claim_number="PC-002",
        currency="USD",
        status="draft",
        period_from=date(2026, 5, 1),
        period_to=date(2026, 5, 31),
    )
    pg_session.add(other)
    await pg_session.flush()
    await service.include_payment_applications(claim.id, [pay_app.id])

    with pytest.raises(HTTPException) as refused:
        await service.include_payment_applications(other.id, [pay_app.id])
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "pay_application_in_other_claim"
    assert await _pay_app_claim(pg_session, pay_app.id) == claim.id


async def test_a_currency_mismatch_is_refused_and_takes_the_whole_request_with_it(pg_session) -> None:
    from app.modules.subcontractors.models import PaymentApplication
    from app.modules.subcontractors.service import SubcontractorService

    world = await _world(pg_session, suffix=uuid.uuid4().hex[:8])
    service = SubcontractorService(pg_session)
    claim, good = world["claim"], world["pay_app"]
    euro = PaymentApplication(
        id=uuid.uuid4(),
        agreement_id=world["agreement"].id,
        application_number="PA-2",
        status="finance_approved",
        currency="EUR",
        gross_amount=Decimal("100"),
        net_amount=Decimal("90"),
        period_end=date(2026, 4, 30),
    )
    pg_session.add(euro)
    await pg_session.flush()

    with pytest.raises(HTTPException) as refused:
        await service.include_payment_applications(claim.id, [good.id, euro.id])
    assert refused.value.status_code == 422
    assert refused.value.detail["code"] == "currency_mismatch"
    # All or nothing: the good one was checked first and still not linked.
    assert await _pay_app_claim(pg_session, good.id) is None
    assert await _pay_app_claim(pg_session, euro.id) is None


async def test_submitting_the_claim_runs_the_subcontract_rules(pg_session, monkeypatch) -> None:
    from app.modules.contracts import claim_context
    from app.modules.contracts.service import ContractsService
    from app.modules.contracts.validators import register_contracts_validation_rules
    from app.modules.subcontractors.claim_rules import register_sub_rollup_context, register_sub_rollup_rules
    from app.modules.subcontractors.service import SubcontractorService

    # Startup's two registrations, done here the same way: the rules, and the
    # rollup they read, which reaches contracts only through its registry.
    # The registry is swapped for this test so the provider does not outlive it.
    monkeypatch.setattr(claim_context, "_providers", {})
    register_contracts_validation_rules()
    register_sub_rollup_rules()
    assert register_sub_rollup_context() is True
    world = await _world(pg_session, suffix=uuid.uuid4().hex[:8], requires_lien_waiver=True)
    claim, pay_app = world["claim"], world["pay_app"]
    await SubcontractorService(pg_session).include_payment_applications(claim.id, [pay_app.id])

    report = await ContractsService(pg_session).run_claim_rules(claim)
    blocking = {result.rule_id for result in report.errors}
    # The agreement requires a waiver and none is on file: the claim may not go out.
    assert "pay_application.sub_waiver_missing" in blocking


# ── Finance approval sets what each line bills ──────────────────────────────


async def _foreman_approved_world(session: Any) -> dict[str, Any]:
    return await _world(
        session, suffix=uuid.uuid4().hex[:8], pay_app_status="foreman_approved", line_approved=Decimal("0")
    )


async def _line_approved(session: Any, line_id: uuid.UUID) -> Decimal:
    from sqlalchemy import select

    from app.modules.subcontractors.models import PaymentApplicationLine

    return (
        await session.execute(
            select(PaymentApplicationLine.approved_amount).where(PaymentApplicationLine.id == line_id)
        )
    ).scalar_one()


async def test_a_lowered_approval_is_what_the_claim_rollup_bills(pg_session) -> None:
    from app.modules.subcontractors.schemas import ApprovedLineAmount
    from app.modules.subcontractors.service import SubcontractorService

    world = await _foreman_approved_world(pg_session)
    claim, pay_app, pa_line = world["claim"], world["pay_app"], world["pa_line"]
    service = SubcontractorService(pg_session)
    line_id, pay_app_id, claim_id = pa_line.id, pay_app.id, claim.id

    approved = await service.approve_payment_application_finance(
        pay_app_id, user_id=str(uuid.uuid4()), lines=[ApprovedLineAmount(line_id=line_id, approved_amount="1500")]
    )
    assert approved.status == "finance_approved"
    assert await _line_approved(pg_session, line_id) == Decimal("1500")

    await service.include_payment_applications(claim_id, [pay_app_id])
    rollup = await service.claim_rollup(claim_id)
    [line] = rollup["lines"]
    assert Decimal(str(line["sub_period_approved"])) == Decimal("1500")


async def test_an_approval_above_the_claim_is_refused_and_changes_nothing(pg_session) -> None:
    from app.modules.subcontractors.schemas import ApprovedLineAmount
    from app.modules.subcontractors.service import SubcontractorService

    world = await _foreman_approved_world(pg_session)
    line_id, pay_app_id = world["pa_line"].id, world["pay_app"].id

    with pytest.raises(HTTPException) as refused:
        await SubcontractorService(pg_session).approve_payment_application_finance(
            pay_app_id,
            user_id=str(uuid.uuid4()),
            lines=[ApprovedLineAmount(line_id=line_id, approved_amount="2000.01")],
        )
    assert refused.value.status_code == 422
    assert refused.value.detail["code"] == "approved_above_claimed"
    assert await _line_approved(pg_session, line_id) == Decimal("0")
    assert await _pay_app_status(pg_session, pay_app_id) == "foreman_approved"


async def test_a_line_from_another_pay_application_is_refused(pg_session) -> None:
    from app.modules.subcontractors.schemas import ApprovedLineAmount
    from app.modules.subcontractors.service import SubcontractorService

    world = await _foreman_approved_world(pg_session)
    other = await _world(pg_session, suffix=uuid.uuid4().hex[:8])
    pay_app_id, foreign_line = world["pay_app"].id, other["pa_line"].id

    with pytest.raises(HTTPException) as refused:
        await SubcontractorService(pg_session).approve_payment_application_finance(
            pay_app_id, user_id=str(uuid.uuid4()), lines=[ApprovedLineAmount(line_id=foreign_line, approved_amount="1")]
        )
    assert refused.value.status_code == 422
    assert refused.value.detail["code"] == "line_not_on_payment_application"
    assert await _pay_app_status(pg_session, pay_app_id) == "foreman_approved"
    # The other pay application's line was not touched either.
    assert await _line_approved(pg_session, foreign_line) == Decimal("2000")


def _app(session: Any, owner_id: str) -> Any:
    """The subcontractor router on its own app, answering as ``owner_id``."""
    from fastapi import FastAPI

    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.subcontractors.permissions import register_subcontractors_permissions
    from app.modules.subcontractors.router import router as subs_router

    register_subcontractors_permissions()
    app = FastAPI()
    app.include_router(subs_router, prefix="/v1/subcontractors")

    async def _session():
        yield session

    async def _user() -> str:
        return owner_id

    async def _payload() -> dict:
        return {"sub": owner_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@pytest.mark.parametrize("body", [None, {}, {"lines": []}])
async def test_an_approval_that_names_no_amounts_approves_each_line_as_claimed(pg_session, body) -> None:
    # Over HTTP, because "no body" and "{}" are two different requests that
    # must mean the same approval.
    import httpx

    world = await _foreman_approved_world(pg_session)
    line_id, pay_app_id = world["pa_line"].id, world["pay_app"].id
    owner_id = str(world["project"].owner_id)
    app = _app(pg_session, owner_id)

    url = f"/v1/subcontractors/payment-applications/{pay_app_id}/approve-finance"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await (client.post(url) if body is None else client.post(url, json=body))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "finance_approved"
    assert resp.json()["finance_approved_by"] == owner_id
    assert await _line_approved(pg_session, line_id) == Decimal("2000")


async def _pay_app_status(session: Any, pay_app_id: uuid.UUID) -> str:
    from sqlalchemy import select

    from app.modules.subcontractors.models import PaymentApplication

    return (
        await session.execute(select(PaymentApplication.status).where(PaymentApplication.id == pay_app_id))
    ).scalar_one()


async def test_a_lowered_approval_is_what_gets_paid_and_what_retention_holds(pg_session, monkeypatch) -> None:
    from app.modules.subcontractors import service as service_module
    from app.modules.subcontractors.models import PaymentApplication, RetentionLedger
    from app.modules.subcontractors.schemas import ApprovedLineAmount
    from app.modules.subcontractors.service import SubcontractorService

    published: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        service_module.event_bus,
        "publish_detached",
        lambda name, data, **_kw: published.append((name, data)),
    )
    # The paid event waits for the commit, which this rolled-back session never makes.
    monkeypatch.setattr(
        service_module,
        "publish_after_commit",
        lambda _session, name, data, **_kw: published.append((name, data)),
    )

    world = await _foreman_approved_world(pg_session)
    agreement, pay_app, pa_line = world["agreement"], world["pay_app"], world["pa_line"]
    # The accrual booked when the pay application was submitted: 10% of 2000.
    pg_session.add(
        RetentionLedger(
            id=uuid.uuid4(),
            agreement_id=agreement.id,
            payment_application_id=pay_app.id,
            accrued_amount=Decimal("200"),
            released_amount=Decimal("0"),
        )
    )
    await pg_session.flush()

    service = SubcontractorService(pg_session)
    await service.approve_payment_application_finance(
        pay_app.id,
        user_id=str(uuid.uuid4()),
        lines=[ApprovedLineAmount(line_id=pa_line.id, approved_amount="1500")],
    )

    from sqlalchemy import select

    row = (
        await pg_session.execute(
            select(
                PaymentApplication.gross_amount,
                PaymentApplication.net_amount,
                PaymentApplication.approved_gross_amount,
                PaymentApplication.approved_retention_amount,
                PaymentApplication.approved_net_amount,
            ).where(PaymentApplication.id == pay_app.id)
        )
    ).one()
    # The claim stays as the sub sent it; the waiver gate reads that net.
    assert (Decimal(str(row.gross_amount)), Decimal(str(row.net_amount))) == (Decimal("2000"), Decimal("1800"))
    assert Decimal(str(row.approved_gross_amount)) == Decimal("1500")
    assert Decimal(str(row.approved_retention_amount)) == Decimal("150")
    assert Decimal(str(row.approved_net_amount)) == Decimal("1350")
    # Retention is held on what was approved, so releasing it later cannot
    # hand back retention on money nobody approved.
    assert await service.retention_balance(agreement.id) == Decimal("150")

    await service.mark_paid(pay_app.id)
    [paid] = [data for name, data in published if name == "subcontractors.payment_application.paid"]
    assert paid["net_amount"] == "1350.00"
    assert paid["claimed_net_amount"] == "1800.00"


async def test_a_lien_waiver_must_be_in_the_pay_applications_currency(pg_session, tmp_path, monkeypatch) -> None:
    # The same refusal is asserted in tests/modules, which no lane of CI runs;
    # this copy puts it in the PostgreSQL lane, against a real database.
    import httpx

    from app.modules.subcontractors import router as subs_router_mod

    monkeypatch.setattr(subs_router_mod, "LIEN_WAIVERS_DIR", tmp_path / "waivers")
    world = await _world(pg_session, suffix=uuid.uuid4().hex[:8], requires_lien_waiver=True)
    sub_id = world["agreement"].subcontractor_id
    pay_app_id = world["pay_app"].id
    app = _app(pg_session, str(world["project"].owner_id))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
            data={
                "waiver_type": "conditional_partial",
                "payment_application_id": str(pay_app_id),
                "amount": "1800.00",
                "currency": "EUR",
            },
            files={"file": ("waiver.pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "application/pdf")},
        )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "currency_mismatch"

    listed = await _waivers_of(pg_session, sub_id)
    # Refused before the file was stored: nothing is on record.
    assert listed == []


async def _waivers_of(session: Any, sub_id: uuid.UUID) -> list[Any]:
    from sqlalchemy import select

    from app.modules.subcontractors.models import LienWaiver

    return list(
        (await session.execute(select(LienWaiver).where(LienWaiver.subcontractor_id == sub_id))).scalars().all()
    )


async def test_the_lines_of_a_pay_application_answer_with_a_page(pg_session) -> None:
    # Over HTTP, because the envelope is the thing being asserted: a forward
    # reference to the row class parses fine and fails when Pydantic builds
    # the model, which only a real response catches.
    import httpx

    from app.modules.subcontractors.models import PaymentApplicationLine

    world = await _world(pg_session, suffix=uuid.uuid4().hex[:8])
    pay_app, package = world["pay_app"], world["package"]
    for _ in range(2):
        pg_session.add(
            PaymentApplicationLine(
                id=uuid.uuid4(),
                payment_application_id=pay_app.id,
                work_package_id=package.id,
                claimed_amount=Decimal("500"),
                certified_amount=Decimal("0"),
                approved_amount=Decimal("0"),
            )
        )
    await pg_session.flush()

    app = _app(pg_session, str(world["project"].owner_id))
    url = f"/v1/subcontractors/payment-applications/{pay_app.id}/lines"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        whole = await client.get(url)
        short = await client.get(url, params={"offset": 1, "limit": 1})

    assert whole.status_code == 200, whole.text
    body = whole.json()
    assert len(body["items"]) == 3
    assert body["total"] == 3
    assert (body["offset"], body["limit"]) == (0, 200)

    # The count is of the pay application's lines, not of the page: a reader
    # holding one row can tell there are two more.
    page = short.json()
    assert len(page["items"]) == 1
    assert page["total"] == 3
    assert (page["offset"], page["limit"]) == (1, 1)
    assert page["items"][0]["id"] != body["items"][0]["id"]
