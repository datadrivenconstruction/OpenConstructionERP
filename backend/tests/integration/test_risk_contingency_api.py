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
