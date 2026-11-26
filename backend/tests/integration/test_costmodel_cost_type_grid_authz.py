"""Cost-type grid over the real app: committed per budget line and type, totals, access.

Scenario (project in EUR), cost code 1.01 "Mobilization" with three budget lines:
    * labor          budget 400, actual 100;
    * material       budget 200, an issued PO item of 250 booked to this line;
    * subcontractor  budget 300, an active subcontract agreement of 350 booked to this line.

Expected: committed lands on the named lines only (material 250, subcontractor 350, labor 0),
the cost code subtotal and the per-type subtotals add up to the grid total, and a viewer
(an owner without write permission) can read the grid but cannot book a line to a budget line.

The ``authz`` in the file name keeps it in the PR-gating tenant-isolation lane.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

API = "/api/v1"
D = Decimal


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


async def _register(client: AsyncClient, *, role: str) -> dict:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"ctgrid-{uuid.uuid4().hex[:8]}@cost-types.io"
    password = f"CostTypes{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        f"{API}/users/auth/register",
        json={"email": email, "password": password, "full_name": "Cost type tester"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role=role))
        await s.commit()
    login = await client.post(f"{API}/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"id": reg.json()["id"], "headers": {"Authorization": f"Bearer {login.json()['access_token']}"}}


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/projects/",
        json={
            "name": f"CostTypes {uuid.uuid4().hex[:6]}",
            "description": "cost type grid",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def scenario(http_client):
    admin = await _register(http_client, role="admin")
    project_id = await _project(http_client, admin["headers"])
    other_project_id = await _project(http_client, admin["headers"])

    from app.database import async_session_factory
    from app.modules.costmodel.models import BudgetLine, CostLine
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    pid = uuid.UUID(project_id)
    async with async_session_factory() as s:
        cl = CostLine(project_id=pid, code="1.01", description="Mobilization", currency="EUR")
        s.add(cl)
        await s.flush()
        lines = {}
        for category, planned, actual in (
            ("labor", "400", "100"),
            ("material", "200", "0"),
            ("subcontractor", "300", "0"),
        ):
            line = BudgetLine(
                project_id=pid,
                cost_line_id=cl.id,
                category=category,
                description=f"1.01 {category}",
                planned_amount=planned,
                committed_amount="0",
                actual_amount=actual,
                forecast_amount=planned,
                currency="EUR",
            )
            s.add(line)
            lines[category] = line
        foreign = BudgetLine(
            project_id=uuid.UUID(other_project_id),
            category="material",
            description="other project",
            planned_amount="1",
            committed_amount="0",
            actual_amount="0",
            forecast_amount="1",
            currency="EUR",
        )
        s.add(foreign)
        await s.flush()

        po = PurchaseOrder(
            project_id=pid,
            po_number=f"PO-{uuid.uuid4().hex[:6]}",
            currency_code="EUR",
            status="issued",
            amount_total="250",
        )
        s.add(po)
        await s.flush()
        s.add(
            PurchaseOrderItem(
                po_id=po.id,
                description="Site cabin",
                quantity="1",
                unit_rate="250",
                amount="250",
                cost_line_id=cl.id,
                budget_line_id=lines["material"].id,
            )
        )
        await s.commit()
        ids = {k: str(v.id) for k, v in lines.items()}
        ids["foreign"] = str(foreign.id)

    sub = await http_client.post(
        f"{API}/subcontractors/subcontractors/",
        json={"legal_name": f"Site Services {uuid.uuid4().hex[:6]}", "country": "DE"},
        headers=admin["headers"],
    )
    assert sub.status_code == 201, sub.text
    agreement = await http_client.post(
        f"{API}/subcontractors/agreements/",
        json={
            "subcontractor_id": sub.json()["id"],
            "project_id": project_id,
            "title": "Mobilization package",
            "total_value": "350.00",
            "currency": "EUR",
            "budget_line_id": ids["subcontractor"],
        },
        headers=admin["headers"],
    )
    assert agreement.status_code == 201, agreement.text
    assert agreement.json()["budget_line_id"] == ids["subcontractor"]

    from sqlalchemy import update

    from app.modules.subcontractors.models import SubcontractAgreement

    async with async_session_factory() as s:
        await s.execute(
            update(SubcontractAgreement)
            .where(SubcontractAgreement.id == uuid.UUID(agreement.json()["id"]))
            .values(status="active")
        )
        await s.commit()

    return {
        "admin": admin,
        "project_id": project_id,
        "ids": ids,
        "agreement_id": agreement.json()["id"],
        "subcontractor_id": sub.json()["id"],
    }


async def _grid(client: AsyncClient, headers: dict[str, str], project_id: str):
    resp = await client.get(f"{API}/costmodel/projects/{project_id}/5d/cost-type-grid/", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _money(value) -> Decimal:
    return D(str(value))


@pytest.mark.asyncio
async def test_committed_rolls_into_the_named_budget_line_only(http_client, scenario):
    body = await _grid(http_client, scenario["admin"]["headers"], scenario["project_id"])
    assert [g["cost_code"] for g in body["groups"]] == ["1.01"]
    rows = {r["cost_type"]: r for r in body["groups"][0]["rows"]}
    assert _money(rows["labor"]["committed"]) == D("0")
    assert _money(rows["material"]["committed"]) == D("250")
    assert _money(rows["subcontractor"]["committed"]) == D("350")
    assert rows["material"]["committed_from_documents"] is True
    assert rows["labor"]["committed_from_documents"] is False
    # EAC is the forecast raised to what is already committed or spent.
    assert (_money(rows["material"]["eac"]), rows["material"]["eac_basis"]) == (D("250"), "committed")
    assert (_money(rows["subcontractor"]["eac"]), rows["subcontractor"]["eac_basis"]) == (D("350"), "committed")
    assert (_money(rows["labor"]["eac"]), rows["labor"]["eac_basis"]) == (D("400"), "forecast")


@pytest.mark.asyncio
async def test_totals_reconcile_by_code_by_type_and_overall(http_client, scenario):
    body = await _grid(http_client, scenario["admin"]["headers"], scenario["project_id"])
    fields = ("budget", "committed", "actual", "forecast", "eac", "variance")
    total = {f: _money(body["total"][f]) for f in fields}
    assert total["budget"] == D("900")
    assert total["committed"] == D("600")
    assert total["actual"] == D("100")
    assert total["eac"] == D("400") + D("250") + D("350")
    assert total["variance"] == total["budget"] - total["eac"]
    for f in fields:
        assert sum(_money(g["subtotal"][f]) for g in body["groups"]) == total[f]
        assert sum(_money(t["totals"][f]) for t in body["by_type"]) == total[f]
        assert sum(_money(r[f]) for g in body["groups"] for r in g["rows"]) == total[f]
    assert body["line_count"] == 3
    # The same committed the dashboard reports: the grid and the 5D surfaces never disagree.
    dash = await http_client.get(
        f"{API}/costmodel/projects/{scenario['project_id']}/5d/dashboard/", headers=scenario["admin"]["headers"]
    )
    assert dash.status_code == 200, dash.text
    assert _money(dash.json()["total_committed"]) == total["committed"]


@pytest.mark.asyncio
async def test_type_filter_narrows_rows_and_totals(http_client, scenario):
    resp = await http_client.get(
        f"{API}/costmodel/projects/{scenario['project_id']}/5d/cost-type-grid/",
        params={"cost_type": "material"},
        headers=scenario["admin"]["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert _money(resp.json()["total"]["committed"]) == D("250")
    assert resp.json()["line_count"] == 1


@pytest.mark.asyncio
async def test_a_budget_line_of_another_project_is_refused(http_client, scenario):
    resp = await http_client.patch(
        f"{API}/subcontractors/agreements/{scenario['agreement_id']}",
        json={"budget_line_id": scenario["ids"]["foreign"]},
        headers=scenario["admin"]["headers"],
    )
    assert resp.status_code == 422, resp.text

    po = await http_client.post(
        f"{API}/procurement/",
        json={
            "project_id": scenario["project_id"],
            "items": [
                {
                    "description": "x",
                    "quantity": "1",
                    "unit_rate": "5",
                    "amount": "5",
                    "budget_line_id": scenario["ids"]["foreign"],
                }
            ],
        },
        headers=scenario["admin"]["headers"],
    )
    assert po.status_code == 422, po.text


@pytest.mark.asyncio
async def test_viewer_reads_the_grid_but_cannot_write_links(http_client, scenario):
    viewer = await _register(http_client, role="viewer")
    # Make the viewer the project owner so project access is not what stops the writes.
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        await s.execute(
            update(Project)
            .where(Project.id == uuid.UUID(scenario["project_id"]))
            .values(owner_id=uuid.UUID(viewer["id"]))
        )
        await s.commit()

    body = await _grid(http_client, viewer["headers"], scenario["project_id"])
    assert _money(body["total"]["budget"]) == D("900")

    patch = await http_client.patch(
        f"{API}/subcontractors/agreements/{scenario['agreement_id']}",
        json={"budget_line_id": scenario["ids"]["material"]},
        headers=viewer["headers"],
    )
    assert patch.status_code == 403, patch.text
    post = await http_client.post(
        f"{API}/procurement/",
        json={
            "project_id": scenario["project_id"],
            "items": [
                {
                    "description": "x",
                    "quantity": "1",
                    "unit_rate": "5",
                    "amount": "5",
                    "budget_line_id": scenario["ids"]["labor"],
                }
            ],
        },
        headers=viewer["headers"],
    )
    assert post.status_code == 403, post.text


@pytest.mark.asyncio
async def test_an_outsider_cannot_read_the_grid(http_client, scenario):
    outsider = await _register(http_client, role="viewer")
    resp = await http_client.get(
        f"{API}/costmodel/projects/{scenario['project_id']}/5d/cost-type-grid/", headers=outsider["headers"]
    )
    assert resp.status_code in (403, 404), resp.text
