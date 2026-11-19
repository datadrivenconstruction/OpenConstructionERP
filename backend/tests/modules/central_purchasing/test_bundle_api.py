"""Central purchasing end to end: the DE drywall bundle awarded into three contracts, the US ready-mix
framework with call-offs, and a project team that sees only its own share."""

from __future__ import annotations

import uuid
from decimal import Decimal as D

import pytest
from httpx import AsyncClient
from tests.modules.central_purchasing.conftest import register_user

API = "/api/v1/central-purchasing"


async def _project(client: AsyncClient, header: dict, name: str, currency: str = "EUR") -> str:
    resp = await client.post("/api/v1/projects/", json={"name": name, "currency": currency}, headers=header)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _entity(code: str, country: str, currency: str) -> uuid.UUID:
    from app.database import async_session_factory
    from app.modules.legal_entities.models import LegalEntity

    async with async_session_factory() as session:
        row = LegalEntity(
            code=f"{code}{uuid.uuid4().hex[:4]}", name=code, country_code=country, functional_currency=currency
        )
        session.add(row)
        await session.commit()
        return row.id


async def _set_project(project_id: str, **values) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as session:
        await session.execute(update(Project).where(Project.id == uuid.UUID(project_id)).values(**values))
        await session.commit()


async def _cost_line(project_id: str, code: str, planned: str | None = None) -> str:
    from app.database import async_session_factory
    from app.modules.costmodel.models import BudgetLine, CostLine

    async with async_session_factory() as session:
        line = CostLine(project_id=uuid.UUID(project_id), code=code, description=f"KG {code}")
        session.add(line)
        await session.flush()
        if planned is not None:
            session.add(
                BudgetLine(
                    project_id=uuid.UUID(project_id),
                    cost_line_id=line.id,
                    category="subcontractor",
                    planned_amount=planned,
                )
            )
        await session.commit()
        return str(line.id)


async def _committed(project_id: str) -> dict[str, D]:
    from app.database import async_session_factory
    from app.modules.costmodel.repository import CostSpineRepository

    async with async_session_factory() as session:
        return await CostSpineRepository(session).committed_by_cost_line(uuid.UUID(project_id))


async def _activate_contracts(ids: list[str]) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.contracts.models import Contract

    async with async_session_factory() as session:
        await session.execute(
            update(Contract).where(Contract.id.in_([uuid.UUID(i) for i in ids])).values(status="active")
        )
        await session.commit()


@pytest.mark.asyncio
async def test_de_drywall_three_contracts_each_in_its_own_project(client: AsyncClient, buyer) -> None:
    _, header = buyer
    hb, tb = await _entity("HB", "DE", "EUR"), await _entity("TB", "DE", "EUR")
    p1, p2, p3 = [await _project(client, header, f"Haus {n}") for n in (1, 2, 3)]
    for pid, ent in ((p1, hb), (p2, tb), (p3, hb)):
        await _set_project(pid, legal_entity_id=ent, country_code="DE")
    cl = {
        pid: (await _cost_line(pid, "342"), await _cost_line(pid, "353", "56000.00" if pid == p2 else None))
        for pid in (p1, p2, p3)
    }
    # P2's budget: 56,000 on KG 342 plus 56,000 on KG 353 = 112,000.
    from app.database import async_session_factory
    from app.modules.costmodel.models import BudgetLine

    async with async_session_factory() as session:
        session.add(
            BudgetLine(
                project_id=uuid.UUID(p2),
                cost_line_id=uuid.UUID(cl[p2][0]),
                category="subcontractor",
                planned_amount="56000.00",
            )
        )
        await session.commit()

    resp = await client.post(f"{API}/", json={"title": "Trockenbau Einkauf 2027", "currency": "EUR"}, headers=header)
    assert resp.status_code == 201, resp.text
    bid = resp.json()["id"]
    for pid in (p1, p2, p3):
        resp = await client.post(f"{API}/{bid}/projects", json={"project_id": pid}, headers=header)
        assert resp.status_code == 200, resp.text
    bps = {p["project_id"]: p["id"] for p in resp.json()["projects"]}
    assert {p["legal_entity_id"] for p in resp.json()["projects"]} == {str(hb), str(tb)}

    for code, desc, qty, rate, kg, shares in (
        ("L1", "Partition 100 mm", "12000", "28.50", "342", ("5200", "2800", "4000")),
        ("L2", "Suspended ceiling", "4500", "41.20", "353", ("2000", "1000", "1500")),
    ):
        resp = await client.post(
            f"{API}/{bid}/lines",
            json={
                "code": code,
                "description": desc,
                "unit": "m2",
                "quantity": qty,
                "unit_rate": rate,
                "cost_code": kg,
                "shares": [
                    {"bundle_project_id": bps[p], "quantity": q} for p, q in zip((p1, p2, p3), shares, strict=True)
                ],
            },
            headers=header,
        )
        assert resp.status_code == 200, resp.text
    detail = resp.json()
    # Cost lines found by the KG code in each project.
    assert all(s["cost_line_code"] in ("342", "353") for ln in detail["lines"] for s in ln["shares"])

    resp = await client.post(f"{API}/{bid}/preview", json={"discount_pct": "2"}, headers=header)
    split = resp.json()["split"]
    assert (split["gross"], split["net"], split["reconciles"]) == ("527400.00", "516852.00", True)
    nets = {r["bundle_project_id"]: r["net"] for r in split["rows"]}
    assert [nets[bps[p]] for p in (p1, p2, p3)] == ["225988.00", "118580.00", "172284.00"]
    over = [f for f in resp.json()["findings"] if f["rule_id"] == "bundle.project_over_budget"]
    assert len(over) == 1
    assert "6,580" in over[0]["message"]

    resp = await client.post(
        f"{API}/{bid}/award", json={"vendor_name": "Trockenbau Nord GmbH", "discount_pct": "2"}, headers=header
    )
    assert resp.status_code == 200, resp.text
    awarded = resp.json()
    assert awarded["status"] == "awarded"
    docs = {r["bundle_project_id"]: r["document"] for r in awarded["split"]["rows"]}
    assert {d["type"] for d in docs.values()} == {"contract"}
    assert len({d["id"] for d in docs.values()}) == 3
    assert all(docs[bps[p]]["project_id"] == p for p in (p1, p2, p3))

    # Drafts commit nothing; once active, P1 sees its own 225,988.00 and not the bundle's 516,852.00.
    assert await _committed(p1) == {}
    await _activate_contracts([d["id"] for d in docs.values()])
    committed = await _committed(p1)
    assert sum(committed.values(), D("0")) == D("225988.00")
    assert set(committed) == {cl[p1][0], cl[p1][1]}
    assert sum((await _committed(p2)).values(), D("0")) == D("118580.00")

    # A project team member sees only P2's share and contract, never the bundle.
    member_id, member = await register_user(client, "viewer", "team")
    await _set_project(p2, owner_id=uuid.UUID(member_id))
    assert (await client.get(f"{API}/{bid}", headers=member)).status_code == 403
    mine = (await client.get(f"{API}/my-shares", params={"project_id": p2}, headers=member)).json()
    assert len(mine) == 1
    assert mine[0]["net"] == "118580.00"
    assert mine[0]["over_budget"] is True
    assert mine[0]["document"]["id"] == docs[bps[p2]]["id"]
    assert [ln["quantity"] for ln in mine[0]["lines"]] == ["2800.0000", "1000.0000"]
    assert "225988.00" not in str(mine)
    assert (await client.get(f"{API}/my-shares", params={"project_id": p1}, headers=member)).status_code == 404


@pytest.mark.asyncio
async def test_uk_blank_share_blocks_the_award(client: AsyncClient, buyer) -> None:
    _, header = buyer
    pa, pb = await _project(client, header, "P-A", "GBP"), await _project(client, header, "P-B", "GBP")
    uk = await _entity("UKB", "GB", "GBP")
    for pid in (pa, pb):
        await _set_project(pid, legal_entity_id=uk, country_code="GB")
    bid = (await client.post(f"{API}/", json={"title": "Cable containment"}, headers=header)).json()["id"]
    for pid in (pa, pb):
        resp = await client.post(f"{API}/{bid}/projects", json={"project_id": pid}, headers=header)
    bps = [p["id"] for p in resp.json()["projects"]]
    await client.post(
        f"{API}/{bid}/lines",
        json={
            "code": "L1",
            "unit": "m",
            "quantity": "2400",
            "unit_rate": "18.40",
            "shares": [
                {"bundle_project_id": bps[0], "quantity": "1500"},
                {"bundle_project_id": bps[1], "quantity": "900"},
            ],
        },
        headers=header,
    )
    resp = await client.post(
        f"{API}/{bid}/lines",
        json={
            "code": "L2",
            "unit": "m",
            "quantity": "1100",
            "unit_rate": "9.85",
            "shares": [
                {"bundle_project_id": bps[0], "quantity": "600"},
                {"bundle_project_id": bps[1], "quantity": None},
            ],
        },
        headers=header,
    )
    rules = {f["rule_id"] for f in resp.json()["findings"]}
    assert {"bundle.project_share_missing", "bundle.share_sum_mismatch"} <= rules
    resp = await client.post(
        f"{API}/{bid}/award", json={"vendor_name": "Sparks Ltd", "lump_sum": "52000.00"}, headers=header
    )
    assert resp.status_code == 422, resp.text

    l2 = resp_line = (await client.get(f"{API}/{bid}", headers=header)).json()["lines"][1]["id"]
    del resp_line
    await client.patch(
        f"{API}/{bid}/lines/{l2}", json={"shares": [{"bundle_project_id": bps[1], "quantity": "500"}]}, headers=header
    )
    resp = await client.post(
        f"{API}/{bid}/award", json={"vendor_name": "Sparks Ltd", "lump_sum": "52000.00"}, headers=header
    )
    assert resp.status_code == 200, resp.text
    nets = [r["net"] for r in resp.json()["split"]["rows"]]
    assert nets == ["31685.06", "20314.94"]


@pytest.mark.asyncio
async def test_us_ready_mix_framework_and_call_offs(client: AsyncClient, buyer) -> None:
    _, header = buyer
    t118, t122 = await _project(client, header, "TX-118", "USD"), await _project(client, header, "TX-122", "USD")
    us = await _entity("USB", "US", "USD")
    for pid in (t118, t122):
        await _set_project(pid, legal_entity_id=us, country_code="US")
    cl118, cl122 = await _cost_line(t118, "03 31 00"), await _cost_line(t122, "03 31 00")
    bid = (
        await client.post(
            f"{API}/",
            json={"title": "Ready-mix 4000 psi", "kind": "supply", "mode": "framework_call_off", "currency": "USD"},
            headers=header,
        )
    ).json()["id"]
    for pid in (t118, t122):
        resp = await client.post(f"{API}/{bid}/projects", json={"project_id": pid}, headers=header)
    bps = [p["id"] for p in resp.json()["projects"]]
    for code, rate in (("concrete", "168.00"), ("pump", "14.50")):
        resp = await client.post(
            f"{API}/{bid}/lines",
            json={
                "code": code,
                "unit": "CY",
                "quantity": "3000",
                "unit_rate": rate,
                "cost_code": "03 31 00",
                "shares": [
                    {"bundle_project_id": bps[0], "quantity": "1800"},
                    {"bundle_project_id": bps[1], "quantity": "1200"},
                ],
            },
            headers=header,
        )
    lines = [ln["id"] for ln in resp.json()["lines"]]
    resp = await client.post(f"{API}/{bid}/award", json={"vendor_name": "Lone Star Ready Mix"}, headers=header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["split"]["net"] == "547500.00"
    assert len(body["agreements"]) == 1
    # The agreement commits nothing in the project that holds it.
    assert await _committed(t118) == {}

    resp = await client.post(
        f"{API}/{bid}/call-offs",
        json={
            "project_id": t118,
            "lines": [{"line_id": lines[0], "quantity": "240"}, {"line_id": lines[1], "quantity": "240"}],
        },
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["total"] == "43800.00"
    po_id = resp.json()["document"]["id"]

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.procurement.models import PurchaseOrder

    async with async_session_factory() as session:
        await session.execute(update(PurchaseOrder).where(PurchaseOrder.id == uuid.UUID(po_id)).values(status="issued"))
        await session.commit()
    assert (await _committed(t118)) == {cl118: D("43800.00")}

    # TX-122: 1,100 CY already issued, 150 more goes past the 1,200 share.
    resp = await client.post(
        f"{API}/{bid}/call-offs",
        json={"project_id": t122, "lines": [{"line_id": lines[0], "quantity": "1100"}]},
        headers=header,
    )
    async with async_session_factory() as session:
        await session.execute(
            update(PurchaseOrder)
            .where(PurchaseOrder.id == uuid.UUID(resp.json()["document"]["id"]))
            .values(status="issued")
        )
        await session.commit()
    resp = await client.post(
        f"{API}/{bid}/call-offs",
        json={
            "project_id": t122,
            "lines": [{"line_id": lines[0], "quantity": "150"}, {"line_id": lines[1], "quantity": "150"}],
        },
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["total"] == "27375.00"
    over = [f for f in resp.json()["findings"] if f["rule_id"] == "bundle.calloff_over_share"]
    assert len(over) == 1
    assert "1,250" in over[0]["message"] and "1,200" in over[0]["message"]
    assert cl122

    outsider = await _project(client, header, "TX-999", "USD")
    resp = await client.post(
        f"{API}/{bid}/call-offs",
        json={"project_id": outsider, "lines": [{"line_id": lines[0], "quantity": "10"}]},
        headers=header,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["findings"][0]["rule_id"] == "bundle.calloff_project_not_in_bundle"
