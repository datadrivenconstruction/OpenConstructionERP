# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""HTTP surface of the risk-based contingency routes.

* ``GET    /api/v1/risk/projects/{pid}/contingency``
* ``POST   /api/v1/risk/projects/{pid}/contingency/drawdowns/{risk_id}``
* ``DELETE /api/v1/risk/projects/{pid}/contingency/drawdowns/{risk_id}``

Drawing contingency spends money, so the write routes sit at MANAGER
(``risk.contingency``): an editor who owns the project is refused before the
project check. A manager on another project gets 403/404 and never a 2xx, and
the owner-success controls at the bottom prove the routes are mounted, so a
404 above cannot be a mistyped prefix passing for a guard.

Money crosses the wire as decimal strings, never floats.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.tenant_isolation

RISK = "/api/v1/risk"


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.finance import models as _finance_models  # noqa: F401
        from app.modules.risk import models as _risk_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_user_fields(email: str, **values) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(**values))
        await s.commit()


async def _user(client: AsyncClient, *, tenant: str, role: str) -> dict[str, str]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@risk-contingency.io"
    password = f"RiskCont{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text
    await _set_user_fields(email, is_active=True, role=role)
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _project_with_contingency(client: AsyncClient, headers: dict[str, str], label: str) -> dict[str, str]:
    """A project with one 10 000 EUR contingency line and one occurred risk."""
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"RC-{label} {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    line = await client.post(
        "/api/v1/finance/budgets/",
        json={"project_id": project_id, "wbs_id": "CT", "category": "Contingency", "original_budget": "10000"},
        headers=headers,
    )
    assert line.status_code == 201, line.text

    risk = await client.post(
        f"{RISK}/",
        json={
            "project_id": project_id,
            "title": f"{label} ground water",
            "probability": 0.4,
            "impact_cost": "2500",
            "status": "occurred",
        },
        headers=headers,
    )
    assert risk.status_code == 201, risk.text
    open_risk = await client.post(
        f"{RISK}/",
        json={"project_id": project_id, "title": f"{label} late steel", "probability": 0.5, "impact_cost": "3000"},
        headers=headers,
    )
    assert open_risk.status_code == 201, open_risk.text
    return {"project_id": project_id, "risk_id": risk.json()["id"], "budget_id": line.json()["id"]}


@pytest_asyncio.fixture(scope="module")
async def tenants(http_client):
    # Managers, not admins: they pass RequirePermission("risk.contingency")
    # and miss the admin bypass inside verify_project_access.
    a_headers = await _user(http_client, tenant="a", role="manager")
    b_headers = await _user(http_client, tenant="b", role="manager")
    e_headers = await _user(http_client, tenant="e", role="editor")
    a = await _project_with_contingency(http_client, a_headers, "A")
    b = await _project_with_contingency(http_client, b_headers, "B")
    e = await _project_with_contingency(http_client, e_headers, "E")
    return {"a": {**a, "headers": a_headers}, "b": {**b, "headers": b_headers}, "e": {**e, "headers": e_headers}}


def _drawdown_url(project_id: str, risk_id: str) -> str:
    return f"{RISK}/projects/{project_id}/contingency/drawdowns/{risk_id}"


# ── Cross-project ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_b_cannot_read_a_contingency(http_client, tenants):
    a, b = tenants["a"], tenants["b"]
    resp = await http_client.get(f"{RISK}/projects/{a['project_id']}/contingency", headers=b["headers"])
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.asyncio
async def test_b_cannot_draw_on_a_contingency(http_client, tenants):
    a, b = tenants["a"], tenants["b"]
    resp = await http_client.post(
        _drawdown_url(a["project_id"], a["risk_id"]),
        json={"amount": "100"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), resp.text
    # Nor draw A's risk through B's own project, where B passes the project check.
    resp = await http_client.post(
        _drawdown_url(b["project_id"], a["risk_id"]),
        json={"amount": "100"},
        headers=b["headers"],
    )
    assert resp.status_code == 404, resp.text
    # Nor point B's risk at A's contingency line.
    resp = await http_client.post(
        _drawdown_url(b["project_id"], b["risk_id"]),
        json={"amount": "100", "budget_id": a["budget_id"]},
        headers=b["headers"],
    )
    assert resp.status_code == 404, resp.text
    # A's line is untouched.
    view = await http_client.get(f"{RISK}/projects/{a['project_id']}/contingency", headers=a["headers"])
    assert view.status_code == 200
    assert view.json()["drawn"] == "0.00"


@pytest.mark.asyncio
async def test_editor_cannot_draw_even_on_own_project(http_client, tenants):
    e = tenants["e"]
    resp = await http_client.post(
        _drawdown_url(e["project_id"], e["risk_id"]),
        json={"amount": "100"},
        headers=e["headers"],
    )
    assert resp.status_code == 403, resp.text
    # Reading stays open to the editor.
    view = await http_client.get(f"{RISK}/projects/{e['project_id']}/contingency", headers=e["headers"])
    assert view.status_code == 200, view.text


@pytest.mark.asyncio
async def test_amount_must_be_positive(http_client, tenants):
    b = tenants["b"]
    for bad in ("0", "-5", "1e400", "abc"):
        resp = await http_client.post(
            _drawdown_url(b["project_id"], b["risk_id"]),
            json={"amount": bad},
            headers=b["headers"],
        )
        assert resp.status_code == 422, (bad, resp.text)


# ── Owner-success controls (prove the routes are mounted) ──────────────────


@pytest.mark.asyncio
async def test_owner_reads_confirms_and_reverses(http_client, tenants):
    a = tenants["a"]
    url = f"{RISK}/projects/{a['project_id']}/contingency"
    view = await http_client.get(url, headers=a["headers"])
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["currency"] == "EUR"
    assert body["emv"] == "1500.00"  # only the open risk: 0.5 x 3000
    assert body["allocated"] == "10000.00"
    assert body["state"] == "covered"
    assert [p["risk_id"] for p in body["pending"]] == [a["risk_id"]]
    assert body["pending"][0]["proposed_amount"] == "2500.00"

    confirm = await http_client.post(
        _drawdown_url(a["project_id"], a["risk_id"]),
        json={"amount": "2300", "note": "pumping and dewatering"},
        headers=a["headers"],
    )
    assert confirm.status_code == 200, confirm.text
    after = confirm.json()
    assert after["drawn"] == "2300.00"
    assert after["remaining"] == "7700.00"
    assert after["pending"] == []
    assert after["drawdowns"][0]["note"] == "pumping and dewatering"

    # Replayed: still one drawdown, same totals.
    again = await http_client.post(
        _drawdown_url(a["project_id"], a["risk_id"]),
        json={"amount": "2300", "note": "pumping and dewatering"},
        headers=a["headers"],
    )
    assert again.status_code == 200, again.text
    assert again.json()["drawn"] == "2300.00"
    assert len(again.json()["drawdowns"]) == 1

    # The budget line itself still shows its original money; the drawdown
    # sits on it as a marker the finance page reads.
    budgets = await http_client.get(f"/api/v1/finance/budgets/?project_id={a['project_id']}", headers=a["headers"])
    assert budgets.status_code == 200, budgets.text
    items = budgets.json()["items"] if isinstance(budgets.json(), dict) else budgets.json()
    line = next(i for i in items if i["id"] == a["budget_id"])
    assert line["revised_budget"] in ("10000", "10000.00")
    assert any(k.startswith("contingency_drawdown:") for k in line["metadata"])

    reverse = await http_client.delete(_drawdown_url(a["project_id"], a["risk_id"]), headers=a["headers"])
    assert reverse.status_code == 200, reverse.text
    assert reverse.json()["drawn"] == "0.00"
    gone = await http_client.delete(_drawdown_url(a["project_id"], a["risk_id"]), headers=a["headers"])
    assert gone.status_code == 404, gone.text
