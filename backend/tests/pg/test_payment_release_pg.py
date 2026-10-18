# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release end to end on real PostgreSQL, through the routes a controller uses.

One invented subcontract with a measured schedule line and a lump-sum line,
a certified claim, and two cumulative supplier invoices. The test walks the
terms, the release view with every step to the cent, confirming in order,
the rules, the retention register with a posting, and the measured, invoiced
and paid columns of cost control.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.costmodel.cost_control_service import CostControlService
from app.modules.costmodel.models import CostLine
from app.modules.finance.models import Invoice, InvoiceLineItem, Payment
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

D = Decimal
BASE = "/api/v1/payment-release"


@dataclass
class World:
    session: object
    app: FastAPI
    acting: dict
    project_id: uuid.UUID
    other_project_id: uuid.UUID
    outsider_id: uuid.UUID
    contract_id: uuid.UUID
    lines: dict
    cost_lines: dict
    invoices: dict

    def client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")


def _invoice(project, number: str, on: str, net: str, vat: str, parts: list[tuple[ContractLine, str]]) -> Invoice:
    inv = Invoice(
        project_id=project.id,
        contact_id="k-1",
        invoice_direction="payable",
        invoice_number=number,
        invoice_date=on,
        currency_code="EUR",
        amount_subtotal=D(net),
        tax_amount=D(vat),
        amount_total=D(net) + D(vat),
        status="approved",
    )
    inv.line_items = [
        InvoiceLineItem(
            description=f"Work {n}",
            quantity=D("1"),
            unit_rate=D(amount),
            amount=D(amount),
            vat_rate=D("19"),
            vat_category="S",
            contract_line_id=line.id,
            cost_line_id=line.cost_line_id,
            sort_order=n,
        )
        for n, (line, amount) in enumerate(parts)
    ]
    return inv


@pytest_asyncio.fixture
async def world():
    from app.dependencies import get_current_user_payload, get_session
    from app.modules.payment_release import router as release_router
    from app.modules.payment_release.permissions import register_payment_release_permissions
    from app.modules.payment_release.validators import register_payment_release_rules

    register_payment_release_permissions()
    register_payment_release_rules()
    async with transactional_session() as session:
        tag = uuid.uuid4().hex[:8]
        owner = User(email=f"pr-owner-{tag}@reference.example", hashed_password="x", full_name="Owner")
        outsider = User(email=f"pr-out-{tag}@reference.example", hashed_password="x", full_name="Outsider")
        session.add_all([owner, outsider])
        await session.flush()
        project = Project(name=f"Release {tag}", owner_id=owner.id, currency="EUR", fx_rates=[])
        other = Project(name=f"Other {tag}", owner_id=outsider.id, currency="EUR", fx_rates=[])
        session.add_all([project, other])
        await session.flush()
        cl_a = CostLine(project_id=project.id, code="A", description="Walls", currency="EUR")
        cl_b = CostLine(project_id=project.id, code="B", description="Site setup", currency="EUR")
        session.add_all([cl_a, cl_b])
        await session.flush()
        contract = Contract(
            code=f"SC-{tag}",
            title="Masonry",
            project_id=project.id,
            contract_type="unit_price",
            counterparty_type="subcontractor",
            currency="EUR",
            total_value=D("20000"),
            original_contract_value=D("20000"),
            retention_percent=D("10"),
            status="active",
            terms={},
        )
        session.add(contract)
        await session.flush()
        l1 = ContractLine(
            contract_id=contract.id,
            code="1",
            description="Walls",
            unit="m2",
            quantity=D("100"),
            unit_rate=D("120"),
            total_value=D("12000"),
            cost_line_id=cl_a.id,
            metadata_={},
        )
        l2 = ContractLine(
            contract_id=contract.id,
            code="2",
            description="Site setup",
            unit="LS",
            quantity=D("1"),
            unit_rate=D("8000"),
            total_value=D("8000"),
            cost_line_id=cl_b.id,
            metadata_={},
        )
        session.add_all([l1, l2])
        await session.flush()
        claim = ProgressClaim(contract_id=contract.id, claim_number="1", currency="EUR", status="certified")
        session.add(claim)
        await session.flush()
        session.add_all(
            [
                ProgressClaimLine(
                    progress_claim_id=claim.id,
                    contract_line_id=l1.id,
                    period_completed_qty=D("50"),
                    certified_qty=D("40"),
                    cumulative_completed_value=D("6000"),
                ),
                ProgressClaimLine(
                    progress_claim_id=claim.id,
                    contract_line_id=l2.id,
                    cumulative_completed_value=D("2000"),
                ),
            ]
        )
        inv1 = _invoice(project, "S-1", "2026-03-10", "5000", "950", [(l1, "3000"), (l2, "2000")])
        inv2 = _invoice(project, "S-2", "2026-05-10", "9000", "1710", [(l1, "6000"), (l2, "3000")])
        session.add_all([inv1, inv2])
        await session.flush()
        session.add(Payment(invoice_id=inv1.id, payment_date="2026-03-20", amount=D("5194"), currency_code="EUR"))
        await session.flush()

        app = FastAPI()
        app.include_router(release_router.router, prefix=BASE)
        acting: dict = {"sub": str(owner.id), "role": "manager"}

        async def current_session():
            yield session

        app.dependency_overrides[get_session] = current_session
        app.dependency_overrides[get_current_user_payload] = lambda: dict(acting)
        yield World(
            session=session,
            app=app,
            acting=acting,
            project_id=project.id,
            other_project_id=other.id,
            outsider_id=outsider.id,
            contract_id=contract.id,
            lines={"l1": l1, "l2": l2},
            cost_lines={"a": cl_a, "b": cl_b},
            invoices={"i1": inv1, "i2": inv2},
        )


TERMS = {
    "invoice_mode": "cumulative",
    "retention_percent": "10",
    "retention_release_event": "practical_completion",
    "retention_basis": "gross",
    "rounding_enabled": True,
    "rounding_step": "100",
    "discount_enabled": True,
    "discount_percent": "2",
    "discount_days": 14,
    "discount_applies_to": "both",
    "interim_due_days": 21,
    "final_due_days": 30,
}


async def _ledger(client: AsyncClient, world: World) -> dict:
    r = await client.get(f"{BASE}/projects/{world.project_id}/ledger/")
    assert r.status_code == 200, r.text
    return r.json()


async def test_terms_default_off_then_stored_with_retention_on_the_contract(world: World) -> None:
    async with world.client() as client:
        r = await client.get(f"{BASE}/contracts/{world.contract_id}/terms/")
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["terms_set"] is False
        assert (got["invoice_mode"], got["discount_enabled"], got["rounding_enabled"], got["warranty_enabled"]) == (
            "incremental",
            False,
            False,
            False,
        )
        assert D(got["retention_percent"]) == D("10")

        bad = await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json={**TERMS, "discount_days": 0})
        assert bad.status_code == 422
        r = await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        assert r.status_code == 200, r.text
        assert r.json()["terms_set"] is True
        # The alias is stored as the canonical event, on the contract itself.
        assert r.json()["retention_release_event"] == "substantial_completion"
    contract = await world.session.get(Contract, world.contract_id)
    assert contract.retention_release_event == "substantial_completion"


async def test_the_release_view_shows_every_step_to_the_cent(world: World) -> None:
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        r = await client.patch(
            f"{BASE}/invoices/{world.invoices['i2'].id}/",
            json={"net_deduction": "500", "net_deduction_note": "Agreed reduction", "gross_deduction": "15"},
        )
        assert r.status_code == 200, r.text
        ledger = await _ledger(client, world)

    (block,) = ledger["contracts"]
    assert (block["invoice_mode"], D(block["measured"])) == ("cumulative", D("6800.00"))
    assert block["measured_pct"] == "34.0"
    first, second = block["invoices"]
    f1 = first["figures"]
    assert (D(f1["gross"]), D(f1["retention"]), D(f1["release_before_rounding"])) == (
        D("5950.00"),
        D("595.00"),
        D("5355.00"),
    )
    assert (D(f1["rounding"]), D(f1["release"]), D(f1["discount"]), D(f1["payable"])) == (
        D("55.00"),
        D("5300.00"),
        D("106.00"),
        D("5194.00"),
    )
    assert f1["due_on"] == "2026-03-31" and f1["discount_until"] == "2026-03-24"
    # Paid in full inside the discount period: the discount counts as paid.
    assert (D(first["paid"]), D(first["discount_taken"]), D(first["open_amount"])) == (
        D("5300.00"),
        D("106.00"),
        D("0.00"),
    )
    f2 = second["figures"]
    assert (D(f2["net_after"]), D(f2["vat_deduction"]), D(f2["vat_after"])) == (
        D("8500.00"),
        D("95.00"),
        D("1615.00"),
    )
    assert (D(f2["gross_after"]), D(f2["retention"]), D(f2["previous_releases"])) == (
        D("10100.00"),
        D("1010.00"),
        D("5300.00"),
    )
    assert (D(f2["rounding"]), D(f2["release"]), D(f2["payable"])) == (D("90.00"), D("3700.00"), D("3626.00"))
    assert second["net_deduction_note"] == "Agreed reduction"
    assert [first["counted"], second["counted"]] == [False, True]
    assert D(block["totals"]["invoiced"]) == D("8500.00")
    assert D(block["totals"]["retention_held"]) == D("1010.00")


async def test_releases_go_in_order_and_freeze(world: World) -> None:
    i1, i2 = world.invoices["i1"], world.invoices["i2"]
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        early = await client.post(f"{BASE}/invoices/{i2.id}/release/")
        assert early.status_code == 409 and early.json()["detail"]["problem"] == "earlier_invoice_open"

        world.acting.update({"role": "editor"})
        refused = await client.post(f"{BASE}/invoices/{i1.id}/release/")
        assert refused.status_code == 403
        world.acting.update({"role": "manager"})

        r = await client.post(f"{BASE}/invoices/{i1.id}/release/")
        assert r.status_code == 200, r.text
        assert (r.json()["status"], D(r.json()["release_amount"])) == ("released", D("5300.00"))
        assert (await client.post(f"{BASE}/invoices/{i2.id}/release/")).status_code == 200

        locked = await client.patch(f"{BASE}/invoices/{i1.id}/", json={"net_deduction": "1"})
        assert locked.status_code == 409
        reopen = await client.post(f"{BASE}/invoices/{i1.id}/reopen/")
        assert reopen.status_code == 409 and reopen.json()["detail"]["problem"] == "later_invoice_released"

        # Terms change after the release: the frozen figures stay, V12 says they no longer match.
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json={**TERMS, "retention_percent": "5"})
        ledger = await _ledger(client, world)
        first = ledger["contracts"][0]["invoices"][0]
        assert D(first["figures"]["release"]) == D("5300.00")
        assert first["differs"] is True
        found = (await client.get(f"{BASE}/projects/{world.project_id}/findings/")).json()
    problems = {(f["rule_number"], f["problem"]) for f in found["findings"]}
    assert ("V12", "release_differs") in problems
    # 8500 invoiced against 6800 measured (40 m2 x 120 plus the lump sum's 2000).
    assert ("V16", "invoiced_over_measured") in problems


async def test_a_duplicate_blocks_its_release(world: World) -> None:
    from app.modules.projects.models import Project as P

    project = await world.session.get(P, world.project_id)
    l1 = world.lines["l1"]
    dup = _invoice(project, "s 1", "2026-06-01", "100", "19", [(l1, "100")])
    dup.line_items[0].vat_rate = D("19")
    world.session.add(dup)
    await world.session.flush()
    async with world.client() as client:
        await client.patch(f"{BASE}/invoices/{dup.id}/", json={"kind": "daywork"})
        for inv in (world.invoices["i1"], world.invoices["i2"]):
            assert (await client.post(f"{BASE}/invoices/{inv.id}/release/")).status_code == 200
        r = await client.post(f"{BASE}/invoices/{dup.id}/release/")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["problem"] == "release_blocked_by_findings"
    assert {f["problem"] for f in detail["findings"]} == {"duplicate_number"}


async def test_retention_register_and_a_posting_never_beyond_what_is_held(world: World) -> None:
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        # Only retention withheld from a confirmed release can be paid back.
        for inv in (world.invoices["i1"], world.invoices["i2"]):
            assert (await client.post(f"{BASE}/invoices/{inv.id}/release/")).status_code == 200
        url = f"{BASE}/contracts/{world.contract_id}/retention-postings/"
        body = {"event": "substantial_completion", "event_on": "2026-06-01", "posted_on": "2026-06-15"}
        too_much = await client.post(url, json={**body, "amount": "2000"})
        assert too_much.status_code == 409 and too_much.json()["detail"]["problem"] == "exceeds_held"
        posted = await client.post(url, json={**body, "amount": "1010"})
        assert posted.status_code == 201, posted.text
        register = (await client.get(f"{BASE}/projects/{world.project_id}/retention/")).json()
        (row,) = register["contracts"]
        # Without deductions the second invoice holds 10 % of 10710 gross; 1010 of it is paid back.
        assert (D(row["withheld"]), D(row["posted"]), D(row["held"])) == (D("1071.00"), D("1010.00"), D("61.00"))
        void = await client.post(f"{BASE}/retention-postings/{posted.json()['id']}/void/")
        assert void.status_code == 200 and void.json()["status"] == "void"
        register = (await client.get(f"{BASE}/projects/{world.project_id}/retention/")).json()
        assert D(register["held"]) == D("1071.00")


async def test_cost_control_reads_measured_invoiced_and_paid_per_cost_line(world: World) -> None:
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        await client.patch(f"{BASE}/invoices/{world.invoices['i2'].id}/", json={"net_deduction": "500"})
        for inv in (world.invoices["i1"], world.invoices["i2"]):
            assert (await client.post(f"{BASE}/invoices/{inv.id}/release/")).status_code == 200
        posted = await client.post(
            f"{BASE}/contracts/{world.contract_id}/retention-postings/",
            json={
                "event": "substantial_completion",
                "event_on": "2026-06-01",
                "posted_on": "2026-06-15",
                "amount": "1010",
            },
        )
        assert posted.status_code == 201, posted.text
    report = await CostControlService(world.session).report(world.project_id)
    rows = {r.key: r for r in report.rows}
    a, b = rows[str(world.cost_lines["a"].id)], rows[str(world.cost_lines["b"].id)]
    assert (a.measured, b.measured) == (D("4800.00"), D("2000"))
    # Cumulative: only the latest invoice counts, 8500 net cut 6000:3000 over the two lines.
    assert (a.invoiced, b.invoiced) == (D("5666.67"), D("2833.33"))
    # Paid: invoice 1 (5194 cash + 106 discount) cut 3000:2000, plus the 1010 retention cut like the invoiced money.
    assert a.paid + b.paid == D("5300.00") + D("1010.00")
    assert a.paid == D("3180.00") + D("673.33")
    assert D(report.totals["invoiced"]) == D("8500.00")


async def test_an_outsider_reaches_nothing(world: World) -> None:
    world.acting.update({"sub": str(world.outsider_id), "role": "manager"})
    async with world.client() as client:
        assert (await client.get(f"{BASE}/projects/{world.project_id}/ledger/")).status_code == 404
        assert (await client.get(f"{BASE}/contracts/{world.contract_id}/terms/")).status_code == 404
        r = await client.post(f"{BASE}/invoices/{world.invoices['i1'].id}/release/")
        assert r.status_code == 404
