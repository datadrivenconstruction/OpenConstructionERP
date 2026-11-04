"""Monte Carlo cost risk applied to the estimate as a contingency line, through the API.

Preview -> confirm -> the line is a ``boq.BOQMarkup`` carrying the run's provenance;
a stale preview is refused; editing a line total makes the applied contingency
stale (status and validation rule); undo steps back and finally removes the line.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _auth(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"risk-{unique}@test.io"
    password = f"RiskT{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Risk Tester"}
    )
    assert reg.status_code == 201, reg.text
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    token = ""
    for _ in range(2):
        resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
        token = resp.json().get("access_token", "")
        if token:
            break
        await asyncio.sleep(2)
    assert token, resp.text
    return {"Authorization": f"Bearer {token}"}


async def _bill(client: AsyncClient, auth: dict[str, str]) -> tuple[str, list[str]]:
    resp = await client.post("/api/v1/projects/", json={"name": "Risk", "currency": "EUR"}, headers=auth)
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/boq/boqs/", json={"project_id": resp.json()["id"], "name": "Risk estimate"}, headers=auth
    )
    assert resp.status_code == 201, resp.text
    boq_id = resp.json()["id"]
    ids: list[str] = []
    for i, (qty, rate) in enumerate([(120.0, 85.0), (40.0, 310.0), (900.0, 12.5)], 1):
        resp = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={
                "boq_id": boq_id,
                "ordinal": f"01.{i:03d}",
                "description": f"Line {i}",
                "unit": "m2",
                "quantity": qty,
                "unit_rate": rate,
            },
            headers=auth,
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return boq_id, ids


@pytest.mark.asyncio
async def test_apply_stale_and_undo_round_trip(client: AsyncClient):
    auth = await _auth(client)
    boq_id, ids = await _bill(client, auth)
    url = f"/api/v1/boq/boqs/{boq_id}/cost-risk/contingency/"

    preview = await client.get(url, params={"percentile": 80, "iterations": 1000}, headers=auth)
    assert preview.status_code == 200, preview.text
    s = preview.json()["suggestion"]
    assert preview.json()["applied"] is None
    assert float(s["amount"]) > 0 and s["percentile"] == 80 and 0 < s["confidence"] <= 1

    # The estimator saw another number: refused, nothing written.
    wrong = await client.post(url, json={"percentile": 80, "iterations": 1000, "expected_amount": "1.00"}, headers=auth)
    assert wrong.status_code == 409, wrong.text

    applied = await client.post(
        url, json={"percentile": 80, "iterations": 1000, "expected_amount": s["amount"]}, headers=auth
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["applied"]["amount"] == s["amount"]
    assert body["applied"]["seed"] == s["seed"]
    assert body["applied"]["iterations"] == 1000
    assert body["applied"]["applied_by"]
    assert body["stale"] is False
    assert float(body["drift_amount"]) == 0.0

    markups = (await client.get(f"/api/v1/boq/boqs/{boq_id}/markups/", headers=auth)).json()["markups"]
    line = next(m for m in markups if m["category"] == "contingency")
    assert line["markup_type"] == "fixed"
    assert float(line["fixed_amount"]) == float(s["amount"])

    # Re-apply at P90: same line, P80 kept for undo.
    p90 = (await client.get(url, params={"percentile": 90, "iterations": 1000}, headers=auth)).json()["suggestion"]
    again = await client.post(
        url, json={"percentile": 90, "iterations": 1000, "expected_amount": p90["amount"]}, headers=auth
    )
    assert again.status_code == 200, again.text
    assert again.json()["applied"]["percentile"] == 90
    assert again.json()["applied"]["can_undo_to_previous"] is True
    markups = (await client.get(f"/api/v1/boq/boqs/{boq_id}/markups/", headers=auth)).json()["markups"]
    assert sum(1 for m in markups if m["category"] == "contingency") == 1

    # A line total moves: the applied contingency is stale and drifts.
    resp = await client.patch(f"/api/v1/boq/positions/{ids[0]}", json={"quantity": 400.0}, headers=auth)
    assert resp.status_code == 200, resp.text
    status_now = (await client.get(url, headers=auth)).json()
    assert status_now["stale"] is True
    assert float(status_now["drift_amount"]) != 0.0
    report = await client.post(f"/api/v1/boq/boqs/{boq_id}/validate/", headers=auth)
    assert report.status_code == 200, report.text
    assert "boq.risk.contingency_stale" in report.text

    undo = await client.delete(url, headers=auth)
    assert undo.status_code == 200, undo.text
    assert undo.json()["applied"]["percentile"] == 80
    undo = await client.delete(url, headers=auth)
    assert undo.status_code == 200, undo.text
    assert undo.json()["applied"] is None
    assert (await client.delete(url, headers=auth)).status_code == 404


async def _risks(client: AsyncClient, auth: dict[str, str], boq_id: str) -> list[str]:
    """Put three register risks on the bill's project (one with a three-point band)."""
    boq = (await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)).json()
    project_id = boq["project_id"]
    ids: list[str] = []
    for title, prob, cost in [("Ground water", 0.5, 40000), ("Late steel", 0.3, 25000), ("Crane outage", 0.2, 80000)]:
        resp = await client.post(
            "/api/v1/risk/",
            json={"project_id": project_id, "title": title, "probability": prob, "impact_cost": str(cost)},
            headers=auth,
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return ids


@pytest.mark.asyncio
async def test_register_source_apply_traceability_conflict_and_undo(client: AsyncClient):
    auth = await _auth(client)
    boq_id, _ = await _bill(client, auth)
    risk_ids = await _risks(client, auth, boq_id)
    url = f"/api/v1/boq/boqs/{boq_id}/cost-risk/contingency/"

    preview = await client.get(url, params={"percentile": 80, "iterations": 1000, "source": "register"}, headers=auth)
    assert preview.status_code == 200, preview.text
    s = preview.json()["suggestion"]
    assert s["source"] == "register" and s["items_used"] == 3 and float(s["amount"]) > 0

    wrong = await client.post(
        url,
        json={"percentile": 80, "iterations": 1000, "source": "register", "expected_amount": "1.00"},
        headers=auth,
    )
    assert wrong.status_code == 409, wrong.text

    applied = await client.post(
        url,
        json={"percentile": 80, "iterations": 1000, "source": "register", "expected_amount": s["amount"]},
        headers=auth,
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()["applied"]
    assert body["source"] == "register" and body["items_used"] == 3
    assert {r["id"] for r in body["risk_items"]} == set(risk_ids)
    assert body["register_fingerprint"]
    markups = (await client.get(f"/api/v1/boq/boqs/{boq_id}/markups/", headers=auth)).json()["markups"]
    line = next(m for m in markups if m["category"] == "contingency")
    assert line["metadata"]["risk_run"]["risk_items"] == body["risk_items"]
    assert applied.json()["stale"] is False

    # A register edit makes the line stale and the rule names the register.
    resp = await client.patch(f"/api/v1/risk/{risk_ids[0]}", json={"probability": 0.9}, headers=auth)
    assert resp.status_code == 200, resp.text
    assert (await client.get(url, headers=auth)).json()["stale"] is True
    report = await client.post(f"/api/v1/boq/boqs/{boq_id}/validate/", headers=auth)
    assert "boq.risk.contingency_stale" in report.text and "risk register" in report.text

    # Re-apply from the bill's own ranges as a percentage, then undo back to the register run.
    again = await client.post(url, json={"percentile": 90, "iterations": 1000, "mode": "percentage"}, headers=auth)
    assert again.status_code == 200, again.text
    assert again.json()["applied"]["source"] == "positions" and again.json()["applied"]["mode"] == "percentage"
    markups = (await client.get(f"/api/v1/boq/boqs/{boq_id}/markups/", headers=auth)).json()["markups"]
    assert [m["markup_type"] for m in markups if m["category"] == "contingency"] == ["percentage"]
    undo = await client.delete(url, headers=auth)
    assert undo.status_code == 200, undo.text
    assert undo.json()["applied"]["source"] == "register" and undo.json()["applied"]["mode"] == "fixed"
    markups = (await client.get(f"/api/v1/boq/boqs/{boq_id}/markups/", headers=auth)).json()["markups"]
    assert [m["markup_type"] for m in markups if m["category"] == "contingency"] == ["fixed"]


@pytest.mark.asyncio
async def test_register_source_without_open_risks_is_422(client: AsyncClient):
    auth = await _auth(client)
    boq_id, _ = await _bill(client, auth)
    url = f"/api/v1/boq/boqs/{boq_id}/cost-risk/contingency/"
    resp = await client.post(url, json={"percentile": 80, "iterations": 1000, "source": "register"}, headers=auth)
    assert resp.status_code == 422, resp.text
    assert "no open priced risks" in resp.text


@pytest.mark.asyncio
async def test_percentage_mode_line_follows_a_quantity_edit(client: AsyncClient):
    auth = await _auth(client)
    boq_id, ids = await _bill(client, auth)
    url = f"/api/v1/boq/boqs/{boq_id}/cost-risk/contingency/"
    resp = await client.post(url, json={"percentile": 80, "iterations": 1000, "mode": "percentage"}, headers=auth)
    assert resp.status_code == 200, resp.text
    amount_before = float(resp.json()["applied"]["line_amount"])
    markups = (await client.get(f"/api/v1/boq/boqs/{boq_id}/markups/", headers=auth)).json()["markups"]
    line = next(m for m in markups if m["category"] == "contingency")
    assert line["markup_type"] == "percentage" and line["apply_to"] == "direct_cost"
    assert resp.json()["applied"]["percentage"] == str(float(line["percentage"]))

    patched = await client.patch(f"/api/v1/boq/positions/{ids[0]}", json={"quantity": 400.0}, headers=auth)
    assert patched.status_code == 200, patched.text
    assert float((await client.get(url, headers=auth)).json()["applied"]["line_amount"]) > amount_before


@pytest.mark.asyncio
async def test_other_users_viewer_cannot_apply_or_undo(client: AsyncClient):
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    auth = await _auth(client)
    boq_id, _ = await _bill(client, auth)
    unique = uuid.uuid4().hex[:8]
    email, password = f"viewer-{unique}@test.io", f"ViewT{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Viewer"}
    )
    assert reg.status_code == 201, reg.text
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="viewer", is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    url = f"/api/v1/boq/boqs/{boq_id}/cost-risk/contingency/"
    body = {"percentile": 80, "iterations": 1000, "source": "register", "mode": "percentage"}
    # boq.update is granted to viewers on purpose (they fill their own estimates); another
    # user's bill is refused by the owner check as "not found".
    assert (await client.post(url, json=body, headers=viewer)).status_code == 404
    assert (await client.delete(url, headers=viewer)).status_code == 404


@pytest.mark.asyncio
async def test_default_request_behaves_as_before(client: AsyncClient):
    auth = await _auth(client)
    boq_id, _ = await _bill(client, auth)
    url = f"/api/v1/boq/boqs/{boq_id}/cost-risk/contingency/"
    resp = await client.post(url, json={"percentile": 80, "iterations": 1000}, headers=auth)
    assert resp.status_code == 200, resp.text
    applied = resp.json()["applied"]
    assert applied["source"] == "positions" and applied["mode"] == "fixed" and applied["risk_items"] is None
    markups = (await client.get(f"/api/v1/boq/boqs/{boq_id}/markups/", headers=auth)).json()["markups"]
    assert next(m for m in markups if m["category"] == "contingency")["markup_type"] == "fixed"
