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


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    resp = await client.post(
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
    return uuid.UUID(resp.json()["id"])


@pytest_asyncio.fixture(scope="module")
async def admin_headers(http_client):
    return await _admin_headers(http_client)


@pytest_asyncio.fixture(scope="module")
async def scenario(http_client, admin_headers):
    headers = admin_headers
    project_id = await _create_project(http_client, headers)

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


async def _dashboard_committed(client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID) -> Decimal:
    resp = await client.get(f"{API}/costmodel/projects/{project_id}/5d/dashboard/", headers=headers)
    assert resp.status_code == 200, resp.text
    return Decimal(str(resp.json()["total_committed"]))


@pytest.mark.asyncio
async def test_budget_line_table_and_bi_drilldown_add_up_to_the_dashboard(http_client, scenario):
    headers = scenario["headers"]
    project_id = scenario["project_id"]
    dashboard = await _dashboard_committed(http_client, headers, uuid.UUID(project_id))

    resp = await http_client.get(f"{API}/costmodel/projects/{project_id}/5d/budget-lines/", headers=headers)
    assert resp.status_code == 200, resp.text
    table = {row["category"]: Decimal(str(row["committed_amount"])) for row in resp.json()}
    # The subcontractor row shows its share of the documents, not the typed 400.
    assert table == {"subcontractor": Decimal("1300"), "material": Decimal("200")}
    assert sum(table.values()) == dashboard

    from app.database import async_session_factory
    from app.modules.bi_dashboards.kpis import _cost_split_records

    async with async_session_factory() as s:
        records = await _cost_split_records(s, uuid.UUID(project_id), 100)
    assert sum(Decimal(r["committed_amount"]) for r in records) == dashboard


async def _seed_line(
    s, project_id: uuid.UUID, code: str, *, planned: str = "1000", committed: str = "0", forecast: str | None = None
):
    from app.modules.costmodel.models import BudgetLine, CostLine

    cost_line = CostLine(project_id=project_id, code=code, description=code, currency="EUR")
    s.add(cost_line)
    await s.flush()
    s.add(
        BudgetLine(
            project_id=project_id,
            cost_line_id=cost_line.id,
            category="subcontractor",
            description=code,
            planned_amount=planned,
            committed_amount=committed,
            actual_amount="0",
            forecast_amount=planned if forecast is None else forecast,
            currency="EUR",
        )
    )
    return cost_line


async def _seed_contract(s, project_id, cost_line_id, *, value: str, status_: str, metadata: dict | None = None):
    from app.modules.contracts.models import Contract, ContractLine

    contract = Contract(
        code=f"C-{uuid.uuid4().hex[:6]}",
        title="Subcontract",
        contract_type="lump_sum",
        project_id=project_id,
        total_value=Decimal(value),
        currency="EUR",
        status=status_,
    )
    contract.metadata_ = metadata or {}
    s.add(contract)
    await s.flush()
    line = ContractLine(
        contract_id=contract.id,
        code="SOV-1",
        description="Works",
        unit="lsum",
        quantity=Decimal("1"),
        unit_rate=Decimal(value),
        total_value=Decimal(value),
        cost_line_id=cost_line_id,
    )
    s.add(line)
    await s.flush()
    return contract, line


async def _seed_po(s, project_id, cost_line_id, *, amount: str, metadata: dict | None = None):
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    po = PurchaseOrder(
        project_id=project_id,
        po_number=f"PO-{uuid.uuid4().hex[:6]}",
        currency_code="EUR",
        status="issued",
        amount_total=amount,
    )
    po.metadata_ = metadata or {}
    s.add(po)
    await s.flush()
    s.add(
        PurchaseOrderItem(
            po_id=po.id, description="Supply", quantity="1", unit_rate=amount, amount=amount, cost_line_id=cost_line_id
        )
    )


@pytest.mark.asyncio
async def test_terminated_contract_commits_only_what_was_certified(http_client, admin_headers):
    """A terminated 900 contract with 300 certified (and 500 merely submitted) commits 300."""
    project_id = await _create_project(http_client, admin_headers)

    from app.database import async_session_factory
    from app.modules.contracts.models import ProgressClaim, ProgressClaimLine

    async with async_session_factory() as s:
        cost_line = await _seed_line(s, project_id, "CL-T")
        contract, line = await _seed_contract(s, project_id, cost_line.id, value="900", status_="terminated")
        for number, status_, cumulative in (("PC-1", "certified", "300"), ("PC-2", "submitted", "500")):
            claim = ProgressClaim(contract_id=contract.id, claim_number=number, status=status_, currency="EUR")
            s.add(claim)
            await s.flush()
            s.add(
                ProgressClaimLine(
                    progress_claim_id=claim.id,
                    contract_line_id=line.id,
                    cumulative_completed_value=Decimal(cumulative),
                )
            )
        await s.commit()

    assert await _dashboard_committed(http_client, admin_headers, project_id) == Decimal("300")


@pytest.mark.asyncio
async def test_po_and_contract_from_one_award_count_once(http_client, admin_headers):
    """Contract 800 and PO 1000 from the same award commit 1000, not 1800.

    An unrelated PO of 50 on the same cost line still adds, and a PO of 70 on
    a cost line with no budget line reaches the dashboard and the drill-down.
    """
    project_id = await _create_project(http_client, admin_headers)
    award = {"tender_package_id": str(uuid.uuid4())}

    from app.database import async_session_factory
    from app.modules.costmodel.models import CostLine

    async with async_session_factory() as s:
        cost_line = await _seed_line(s, project_id, "CL-A")
        await _seed_contract(s, project_id, cost_line.id, value="800", status_="active", metadata=award)
        await _seed_po(s, project_id, cost_line.id, amount="1000", metadata=award)
        await _seed_po(s, project_id, cost_line.id, amount="50")
        orphan = CostLine(project_id=project_id, code="CL-U", description="No budget yet", currency="EUR")
        s.add(orphan)
        await s.flush()
        await _seed_po(s, project_id, orphan.id, amount="70")
        await s.commit()

    dashboard = await _dashboard_committed(http_client, admin_headers, project_id)
    assert dashboard == Decimal("1120")

    from app.modules.bi_dashboards.kpis import _cost_split_records

    async with async_session_factory() as s:
        records = await _cost_split_records(s, project_id, 100)
    assert sum(Decimal(r["committed_amount"]) for r in records) == dashboard
    assert [r["committed_amount"] for r in records if r["kind"] == "unbudgeted_commitment"] == ["70"]


@pytest.mark.asyncio
async def test_bi_includes_a_project_without_budget_lines(http_client, admin_headers):
    project_id = await _create_project(http_client, admin_headers)

    from app.database import async_session_factory
    from app.modules.bi_dashboards.kpis import _cost_breakdown_by_category
    from app.modules.costmodel.models import CostLine

    async with async_session_factory() as s:
        cost_line = CostLine(project_id=project_id, code="CL-1", description="Shell", currency="EUR")
        s.add(cost_line)
        await s.flush()
        await _seed_po(s, project_id, cost_line.id, amount="250")
        await s.commit()

    async with async_session_factory() as s:
        by_category, basis, _count, _mixed = await _cost_breakdown_by_category(s, project_id, None)
    assert basis == "committed"
    assert by_category == {"uncategorized": Decimal("250")}


@pytest.mark.asyncio
async def test_portfolio_outturn_reads_the_documents(http_client, admin_headers):
    """No forecast and no typed commitment: the outturn is the issued PO, 1200."""
    project_id = await _create_project(http_client, admin_headers)

    from app.database import async_session_factory

    async with async_session_factory() as s:
        cost_line = await _seed_line(s, project_id, "CL-O", forecast="0")
        await _seed_po(s, project_id, cost_line.id, amount="1200")
        await s.commit()

    resp = await http_client.get(f"{API}/projects/analytics/overview/", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    row = next(p for p in resp.json()["projects"] if p["id"] == str(project_id))
    assert Decimal(str(row["outturn"])) == Decimal("1200")
    assert row["status"] == "over_budget"


@pytest.mark.asyncio
async def test_project_dashboard_shows_the_same_committed_as_the_cost_model(http_client, scenario):
    headers = scenario["headers"]
    project_id = scenario["project_id"]
    five_d = await _dashboard_committed(http_client, headers, uuid.UUID(project_id))

    resp = await http_client.get(f"{API}/projects/{project_id}/dashboard/", headers=headers)
    assert resp.status_code == 200, resp.text
    assert Decimal(str(resp.json()["budget"]["committed"])) == five_d == Decimal("1500")


@pytest.mark.asyncio
async def test_manual_committed_is_refused_on_a_line_fed_by_documents(http_client, scenario):
    headers = scenario["headers"]
    project_id = scenario["project_id"]
    resp = await http_client.get(f"{API}/costmodel/projects/{project_id}/5d/budget-lines/", headers=headers)
    assert resp.status_code == 200, resp.text
    lines = {row["category"]: row for row in resp.json()}
    fed, manual = lines["subcontractor"], lines["material"]
    assert fed["committed_from_documents"] is True
    assert manual["committed_from_documents"] is False

    refused = await http_client.patch(
        f"{API}/costmodel/5d/budget-lines/{fed['id']}", json={"committed_amount": 999}, headers=headers
    )
    assert refused.status_code == 409, refused.text
    assert "purchase orders and contracts" in refused.json()["detail"]

    # Echoing back the reported value (a client saving the whole row) is fine,
    # and so is editing another field of the same line.
    echoed = await http_client.patch(
        f"{API}/costmodel/5d/budget-lines/{fed['id']}",
        json={"committed_amount": fed["committed_amount"], "description": "Shell works (rev)"},
        headers=headers,
    )
    assert echoed.status_code == 200, echoed.text

    # A line without documents keeps accepting a typed committed.
    typed = await http_client.patch(
        f"{API}/costmodel/5d/budget-lines/{manual['id']}", json={"committed_amount": 200}, headers=headers
    )
    assert typed.status_code == 200, typed.text

    assert await _dashboard_committed(http_client, headers, uuid.UUID(project_id)) == Decimal("1500")
