"""Committed on the 5D surfaces comes from linked purchase orders and contracts.

``BudgetLine.committed_amount`` is only ever written by hand, so before this
suite the dashboard, the budget summary and the contract-exposure overcommit
flag stayed at the typed-in figure however many purchase orders were issued or
contracts signed against the budget. They now read the Cost Spine documents.

Scenario (project in EUR):
    * cost line CL1, budget line "subcontractor" planned 1000 with a stale
      manual committed of 400; an issued PO item of 700 and an active contract
      line of 600 point at CL1, plus a DRAFT contract line of 5000 that binds
      nobody and must not count;
    * cost line CL2, budget line "material" planned 500 with a manual
      committed of 200 and no documents, so the manual value still counts.

Expected committed: CL1 = 700 + 600 (the manual 400 is superseded, not added),
CL2 = 200, total 1500, and the subcontractor group is overcommitted
(1300 > 1000) while material is not.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

API = "/api/v1"


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"committed-{uuid.uuid4().hex[:6]}@cost-spine.io"
    password = f"Committed{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        f"{API}/users/auth/register",
        json={"email": email, "password": password, "full_name": "Committed owner"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role="admin"))
        await s.commit()
    login = await client.post(f"{API}/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def scenario(http_client):
    headers = await _admin_headers(http_client)
    resp = await http_client.post(
        f"{API}/projects/",
        json={
            "name": f"Committed {uuid.uuid4().hex[:6]}",
            "description": "committed from the cost spine",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    project_id = uuid.UUID(resp.json()["id"])

    from app.database import async_session_factory
    from app.modules.contracts.models import Contract, ContractLine
    from app.modules.costmodel.models import BudgetLine, CostLine
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    async with async_session_factory() as s:
        cl1 = CostLine(project_id=project_id, code="CL-1", description="Shell works", currency="EUR")
        cl2 = CostLine(project_id=project_id, code="CL-2", description="Finishes", currency="EUR")
        s.add_all([cl1, cl2])
        await s.flush()
        s.add_all(
            [
                BudgetLine(
                    project_id=project_id,
                    cost_line_id=cl1.id,
                    category="subcontractor",
                    description="Shell works",
                    planned_amount="1000",
                    committed_amount="400",
                    actual_amount="0",
                    forecast_amount="1000",
                    currency="EUR",
                ),
                BudgetLine(
                    project_id=project_id,
                    cost_line_id=cl2.id,
                    category="material",
                    description="Finishes",
                    planned_amount="500",
                    committed_amount="200",
                    actual_amount="0",
                    forecast_amount="500",
                    currency="EUR",
                ),
            ]
        )

        po = PurchaseOrder(
            project_id=project_id,
            po_number=f"PO-{uuid.uuid4().hex[:6]}",
            currency_code="EUR",
            status="issued",
            amount_total="700",
        )
        s.add(po)
        await s.flush()
        s.add(
            PurchaseOrderItem(
                po_id=po.id,
                description="Formwork supply",
                quantity="1",
                unit_rate="700",
                amount="700",
                cost_line_id=cl1.id,
            )
        )

        for status_, value in (("active", Decimal("600")), ("draft", Decimal("5000"))):
            contract = Contract(
                code=f"C-{uuid.uuid4().hex[:6]}",
                title=f"Shell subcontract ({status_})",
                contract_type="lump_sum",
                project_id=project_id,
                total_value=value,
                currency="EUR",
                status=status_,
            )
            s.add(contract)
            await s.flush()
            s.add(
                ContractLine(
                    contract_id=contract.id,
                    code="SOV-1",
                    description="Shell works",
                    unit="lsum",
                    quantity=Decimal("1"),
                    unit_rate=value,
                    total_value=value,
                    cost_line_id=cl1.id,
                )
            )
        await s.commit()

    return {"headers": headers, "project_id": str(project_id)}


@pytest.mark.asyncio
async def test_dashboard_committed_counts_linked_po_and_contract_once(http_client, scenario):
    resp = await http_client.get(
        f"{API}/costmodel/projects/{scenario['project_id']}/5d/dashboard/", headers=scenario["headers"]
    )
    assert resp.status_code == 200, resp.text
    # 700 (PO) + 600 (active contract) on CL1, manual 200 on CL2. The stale
    # manual 400 on CL1 and the draft contract must not be added.
    assert Decimal(str(resp.json()["total_committed"])) == Decimal("1500")


@pytest.mark.asyncio
async def test_budget_summary_committed_per_category(http_client, scenario):
    resp = await http_client.get(
        f"{API}/costmodel/projects/{scenario['project_id']}/5d/budget/", headers=scenario["headers"]
    )
    assert resp.status_code == 200, resp.text
    by_cat = {row["category"]: Decimal(str(row["committed"])) for row in resp.json()["categories"]}
    assert by_cat["subcontractor"] == Decimal("1300")
    assert by_cat["material"] == Decimal("200")


@pytest.mark.asyncio
async def test_contract_exposure_flags_overcommit_from_documents(http_client, scenario):
    resp = await http_client.get(
        f"{API}/costmodel/projects/{scenario['project_id']}/5d/contract-exposure/", headers=scenario["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    groups = {g["group"]: g for g in body["groups"]}
    assert Decimal(str(groups["subcontractor"]["committed"])) == Decimal("1300")
    assert groups["subcontractor"]["overcommitted"] is True
    assert Decimal(str(groups["material"]["committed"])) == Decimal("200")
    assert groups["material"]["overcommitted"] is False
    assert Decimal(str(body["total_committed"])) == Decimal("1500")
    assert body["overcommitted_group_count"] == 1


@pytest.mark.asyncio
async def test_bi_cost_split_reads_the_same_committed(http_client, scenario):
    from app.database import async_session_factory
    from app.modules.bi_dashboards.kpis import _cost_breakdown_by_category

    async with async_session_factory() as s:
        by_category, basis, count, _mixed = await _cost_breakdown_by_category(
            s, uuid.UUID(scenario["project_id"]), None
        )
    # No actuals yet, so the tile falls through to committed.
    assert basis == "committed"
    assert count == 2
    assert by_category == {"subcontractor": Decimal("1300"), "material": Decimal("200")}
