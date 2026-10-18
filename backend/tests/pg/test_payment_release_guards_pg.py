# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release on real PostgreSQL: hand figures, ordering guards, roles and project access.

Builds on the invented subcontract of ``test_payment_release_pg`` (two
supplier invoices dated 10 March and 10 May). Gated by ``OE_TEST_DB=pg``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.finance.models import Payment
from app.modules.projects.models import Project
from tests.pg.test_payment_release_pg import BASE, TERMS, World, _invoice, _ledger, world  # noqa: F401

pytestmark = pytest.mark.asyncio

D = Decimal

INCREMENTAL = {
    "invoice_mode": "incremental",
    "retention_percent": "5",
    "retention_release_event": "substantial_completion",
    "retention_basis": "net",
    "discount_enabled": True,
    "discount_percent": "3",
    "discount_days": 10,
    "discount_applies_to": "interim",
}


async def test_incremental_net_retention_and_a_discount_inside_and_outside_its_window(world: World) -> None:  # noqa: F811
    i1, i2 = world.invoices["i1"], world.invoices["i2"]
    # Invoice 1 is paid 5194 on 20 March already; 335 more on 19 March makes 5529, the payable, in the window.
    world.session.add(Payment(invoice_id=i1.id, payment_date="2026-03-19", amount=D("335"), currency_code="EUR"))
    # Invoice 2 is paid its payable on 25 May, after the window that closed on 20 May.
    world.session.add(Payment(invoice_id=i2.id, payment_date="2026-05-25", amount=D("9952.20"), currency_code="EUR"))
    await world.session.flush()
    async with world.client() as client:
        assert (await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=INCREMENTAL)).status_code == 200
        ledger = await _ledger(client, world)
        found = (await client.get(f"{BASE}/projects/{world.project_id}/findings/")).json()
    (contract,) = ledger["contracts"]
    first, second = contract["invoices"]
    f1, f2 = first["figures"], second["figures"]
    # 5950 gross - 250 (5 % of 5000 net) = 5700; 3 % discount 171; payable 5529, until 20 March.
    assert [D(f1[k]) for k in ("retention", "release", "discount", "payable")] == [
        D("250.00"),
        D("5700.00"),
        D("171.00"),
        D("5529.00"),
    ]
    assert f1["discount_until"] == "2026-03-20"
    assert (D(first["discount_taken"]), D(first["paid"]), D(first["open_amount"])) == (D("171.00"), D("5700.00"), 0)
    # 10710 - 450 = 10260, not reduced by invoice 1 (incremental); discount 307.80, payable 9952.20.
    assert [D(f2[k]) for k in ("previous_releases", "retention", "release", "discount", "payable")] == [
        D("5700.00"),
        D("450.00"),
        D("10260.00"),
        D("307.80"),
        D("9952.20"),
    ]
    assert f2["previous_counted"] is False
    # Paid after the window: no discount earned, 307.80 stays open.
    assert (D(second["discount_taken"]), D(second["paid"]), D(second["open_amount"])) == (0, D("9952.20"), D("307.80"))
    totals = contract["totals"]
    assert (D(totals["invoiced"]), D(totals["released"]), D(totals["retention_held"])) == (
        D("14000.00"),
        D("15960.00"),
        D("700.00"),
    )
    late = [f for f in found["findings"] if f["problem"] == "discount_after_deadline"]
    assert [f["element_ref"] for f in late] == [str(i2.id)]


async def test_an_invoice_dated_before_a_released_cumulative_one_waits_for_its_reopening(world: World) -> None:  # noqa: F811
    i1, i2 = world.invoices["i1"], world.invoices["i2"]
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        for inv in (i1, i2):
            assert (await client.post(f"{BASE}/invoices/{inv.id}/release/")).status_code == 200
        # Entered late with an earlier date: S-1 and S-2 were frozen without it.
        project = await world.session.get(Project, world.project_id)
        early = _invoice(project, "S-0", "2026-02-01", "1000", "190", [(world.lines["l1"], "1000")])
        world.session.add(early)
        await world.session.flush()
        refused = await client.post(f"{BASE}/invoices/{early.id}/release/")
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["problem"] == "later_invoice_released"
        assert refused.json()["detail"]["numbers"] == ["S-1", "S-2"]
        for inv in (i2, i1):
            assert (await client.post(f"{BASE}/invoices/{inv.id}/reopen/")).status_code == 200
        assert (await client.post(f"{BASE}/invoices/{early.id}/release/")).status_code == 200
        # S-0: 1190 - 119 = 1071, cut to 1000. S-1 then subtracts it: 5950 - 595 - 1000 = 4355, cut to 4300.
        ledger = await _ledger(client, world)
    s0, s1 = (inv["figures"] for inv in ledger["contracts"][0]["invoices"][:2])
    assert D(s0["release"]) == D("1000.00")
    assert (D(s1["previous_releases"]), D(s1["release"])) == (D("1000.00"), D("4300.00"))


async def test_a_retention_posting_never_lands_under_a_released_cumulative_invoice(world: World) -> None:  # noqa: F811
    i1, i2 = world.invoices["i1"], world.invoices["i2"]
    url = f"{BASE}/contracts/{world.contract_id}/retention-postings/"
    body = {"event": "substantial_completion", "event_on": "2026-03-01", "amount": "100"}
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        assert (await client.post(f"{BASE}/invoices/{i1.id}/release/")).status_code == 200
        same_day = await client.post(url, json={**body, "posted_on": "2026-03-10"})
        assert same_day.status_code == 409 and same_day.json()["detail"]["problem"] == "later_invoice_released"
        posted = await client.post(url, json={**body, "posted_on": "2026-04-01"})
        assert posted.status_code == 201, posted.text
        assert (await client.post(f"{BASE}/invoices/{i2.id}/release/")).status_code == 200
        void_url = f"{BASE}/retention-postings/{posted.json()['id']}/void/"
        refused = await client.post(void_url)
        assert refused.status_code == 409 and refused.json()["detail"]["numbers"] == ["S-2"]
        assert (await client.post(f"{BASE}/invoices/{i2.id}/reopen/")).status_code == 200
        assert (await client.post(void_url)).status_code == 200


async def test_retention_of_an_open_invoice_cannot_be_paid_back(world: World) -> None:  # noqa: F811
    url = f"{BASE}/contracts/{world.contract_id}/retention-postings/"
    body = {"event": "substantial_completion", "event_on": "2026-06-01", "posted_on": "2026-06-15"}
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        # Both invoices open: the ledger shows 1071 held on paper, none of it withheld from a payment yet.
        register = (await client.get(f"{BASE}/projects/{world.project_id}/retention/")).json()
        assert (D(register["held"]), D(register["contracts"][0]["withheld"])) == (0, 0)
        refused = await client.post(url, json={**body, "amount": "100"})
        assert refused.status_code == 409
        assert (refused.json()["detail"]["problem"], D(refused.json()["detail"]["held"])) == ("exceeds_held", 0)
        assert (await client.post(f"{BASE}/invoices/{world.invoices['i1'].id}/release/")).status_code == 200
        # Invoice 1 released withholds 595 (10 % of 5950 gross).
        assert (await client.post(url, json={**body, "amount": "596"})).status_code == 409
        assert (await client.post(url, json={**body, "amount": "595"})).status_code == 201
        register = (await client.get(f"{BASE}/projects/{world.project_id}/retention/")).json()
    (row,) = register["contracts"]
    assert (D(row["withheld"]), D(row["posted"]), D(row["held"])) == (D("595.00"), D("595.00"), 0)


async def test_a_released_invoice_keeps_its_figures_when_the_finance_invoice_changes(world: World) -> None:  # noqa: F811
    i1 = world.invoices["i1"]
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        assert (await client.post(f"{BASE}/invoices/{i1.id}/release/")).status_code == 200
        again = await client.post(f"{BASE}/invoices/{i1.id}/release/")
        assert again.status_code == 409 and again.json()["detail"]["problem"] == "invoice_released"
        i1.amount_subtotal = D("6000")
        i1.tax_amount = D("1140")
        await world.session.flush()
        ledger = await _ledger(client, world)
        found = (await client.get(f"{BASE}/projects/{world.project_id}/findings/")).json()
    first = ledger["contracts"][0]["invoices"][0]
    assert (D(first["figures"]["release"]), D(first["figures"]["net"])) == (D("5300.00"), D("5000.00"))
    assert first["differs"] is True and D(first["computed"]["net"]) == D("6000.00")
    assert any(f["problem"] == "release_differs" and f["element_ref"] == str(i1.id) for f in found["findings"])


async def test_roles_split_terms_from_release(world: World) -> None:  # noqa: F811
    i1 = world.invoices["i1"]
    terms_url = f"{BASE}/contracts/{world.contract_id}/terms/"
    posting_url = f"{BASE}/contracts/{world.contract_id}/retention-postings/"
    posting = {"event": "substantial_completion", "event_on": "2026-06-01", "posted_on": "2026-06-15", "amount": "1"}
    async with world.client() as client:
        world.acting.update({"role": "viewer"})
        assert (await client.get(f"{BASE}/projects/{world.project_id}/ledger/")).status_code == 200
        assert (await client.get(terms_url)).status_code == 200
        assert (await client.put(terms_url, json=TERMS)).status_code == 403
        assert (await client.patch(f"{BASE}/invoices/{i1.id}/", json={"net_deduction": "1"})).status_code == 403

        world.acting.update({"role": "editor"})
        assert (await client.put(terms_url, json=TERMS)).status_code == 200
        assert (await client.patch(f"{BASE}/invoices/{i1.id}/", json={"net_deduction": "1"})).status_code == 200
        assert (await client.post(f"{BASE}/invoices/{i1.id}/release/")).status_code == 403
        assert (await client.post(posting_url, json=posting)).status_code == 403

        world.acting.update({"role": "manager"})
        assert (await client.post(f"{BASE}/invoices/{i1.id}/release/")).status_code == 200
        posted = await client.post(posting_url, json=posting)
        assert posted.status_code == 201, posted.text

        world.acting.update({"role": "editor"})
        assert (await client.post(f"{BASE}/invoices/{i1.id}/reopen/")).status_code == 403
        assert (await client.post(f"{BASE}/retention-postings/{posted.json()['id']}/void/")).status_code == 403


async def test_an_outsider_reaches_no_route_of_the_project(world: World) -> None:  # noqa: F811
    i1 = world.invoices["i1"]
    async with world.client() as client:
        await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        assert (await client.post(f"{BASE}/invoices/{i1.id}/release/")).status_code == 200
        posting = await client.post(
            f"{BASE}/contracts/{world.contract_id}/retention-postings/",
            json={
                "event": "substantial_completion",
                "event_on": "2026-06-01",
                "posted_on": "2026-06-15",
                "amount": "1",
            },
        )
        assert posting.status_code == 201, posting.text
        world.acting.update({"sub": str(world.outsider_id), "role": "manager"})
        pid, cid, iid = world.project_id, world.contract_id, i1.id
        calls = [
            ("get", f"{BASE}/projects/{pid}/ledger/", None),
            ("get", f"{BASE}/projects/{pid}/retention/", None),
            ("get", f"{BASE}/projects/{pid}/findings/", None),
            ("get", f"{BASE}/contracts/{cid}/terms/", None),
            ("put", f"{BASE}/contracts/{cid}/terms/", TERMS),
            (
                "post",
                f"{BASE}/contracts/{cid}/retention-postings/",
                {"event": "substantial_completion", "posted_on": "2026-06-20", "amount": "1"},
            ),
            ("post", f"{BASE}/retention-postings/{posting.json()['id']}/void/", None),
            ("patch", f"{BASE}/invoices/{world.invoices['i2'].id}/", {"net_deduction": "1"}),
            ("post", f"{BASE}/invoices/{world.invoices['i2'].id}/release/", None),
            ("post", f"{BASE}/invoices/{iid}/reopen/", None),
        ]
        for method, url, body in calls:
            r = await client.request(method.upper(), url, json=body)
            assert r.status_code == 404, (method, url, r.status_code, r.text)
        # The outsider's own project lists nothing of the other one.
        own = (await client.get(f"{BASE}/projects/{world.other_project_id}/ledger/")).json()
    assert own["contracts"] == [] and own["other_invoices"] == []
