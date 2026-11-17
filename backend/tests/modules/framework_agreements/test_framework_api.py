"""Framework agreement API end to end: example 1 priced, issued, measured, and the cap guarded."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient


async def _seed_index_and_country(project_id: str) -> None:
    from sqlalchemy import select, update

    from app.database import async_session_factory
    from app.modules.price_index.models import CostIndexPoint, CostIndexSeries
    from app.modules.projects.models import Project

    async with async_session_factory() as session:
        await session.execute(
            update(Project).where(Project.id == uuid.UUID(project_id)).values(country_code="DE", currency="EUR")
        )
        found = (
            await session.execute(select(CostIndexSeries).where(CostIndexSeries.name == "FWK-TEST-TIEFBAU"))
        ).scalar_one_or_none()
        if found is None:
            series = CostIndexSeries(name="FWK-TEST-TIEFBAU", description="test")
            session.add(series)
            await session.flush()
            session.add_all(
                [
                    CostIndexPoint(series_id=series.id, period="2025-01", factor=Decimal("118.4")),
                    CostIndexPoint(series_id=series.id, period="2026-03", factor=Decimal("123.1")),
                ]
            )
        await session.commit()


@pytest_asyncio.fixture(scope="module")
async def agreement(client: AsyncClient, admin_auth, project_id) -> dict:
    _, header = admin_auth
    await _seed_index_and_country(project_id)
    resp = await client.post(
        "/api/v1/framework-agreements/",
        json={
            "project_id": project_id,
            "code": f"A{uuid.uuid4().hex[:4]}",
            "title": "Gas house connections 2025-2028",
            "client_name": "Stadtwerke X",
            "start_date": "2025-01-01",
            "end_date": "2028-12-31",
            "cap_value": "7000.00",
            "escalation_method": "index_ratio",
            "items": [
                {
                    "code": "01.010",
                    "description": "House connection DN32 PE up to 10 m",
                    "unit": "St",
                    "base_rate": "1850.00",
                    "max_qty": "1",
                },
                {"code": "01.020", "description": "Extra trench length", "unit": "m", "base_rate": "96.50"},
                {"code": "01.030", "description": "Asphalt reinstatement", "unit": "m2", "base_rate": "78.40"},
            ],
        },
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pack"]["term_variant"] == "de" and body["pack"]["term_limit"]["years"] == 4
    agreement_id = body["id"]
    periods = (await client.get(f"/api/v1/framework-agreements/{agreement_id}/periods", headers=header)).json()
    assert periods["total"] == len(periods["items"])
    period = periods["items"][0]
    put = await client.put(
        f"/api/v1/framework-agreements/{agreement_id}/periods/{period['id']}",
        json={
            "label": "2025-01",
            "effective_from": "2025-01-01",
            "effective_to": "2028-12-31",
            "method": "index_ratio",
            "base_period": "2025-01",
            "series_refs": [{"series": "FWK-TEST-TIEFBAU"}],
        },
        headers=header,
    )
    assert put.status_code == 200, put.text
    adj = await client.post(
        f"/api/v1/framework-agreements/{agreement_id}/adjustments",
        json={"code": "WE", "label": "Weekend", "kind": "multiplier", "value": "1.15", "condition": "weekend"},
        headers=header,
    )
    assert adj.status_code == 201, adj.text
    act = await client.post(
        f"/api/v1/framework-agreements/{agreement_id}/status", json={"status": "active"}, headers=header
    )
    assert act.status_code == 200, act.text
    return body


_ORDER = {
    "ordered_at": "2026-03-12",
    "tags": ["weekend"],
    "site_label": "Hauptstr. 12",
    "lines": [
        {"code": "01.010", "quantity": "1"},
        {"code": "01.020", "quantity": "14"},
        {"code": "01.030", "quantity": "22"},
    ],
}


@pytest.mark.asyncio
async def test_quote_prices_example_1(client: AsyncClient, admin_auth, agreement) -> None:
    _, header = admin_auth
    resp = await client.post(f"/api/v1/framework-agreements/{agreement['id']}/quote", json=_ORDER, headers=header)
    assert resp.status_code == 200, resp.text
    quote = resp.json()
    assert quote["factor"] == "1.039696"
    assert [ln["unit_rate"] for ln in quote["lines"]] == ["2211.96", "115.38", "93.74"]
    assert quote["net"] == "5889.56"
    assert not quote["blocking"]
    codes = {f["code"] for f in quote["findings"]}
    assert "FWK_CAP_THRESHOLD" in codes


@pytest.mark.asyncio
async def test_unresolved_index_blocks_the_order(client: AsyncClient, admin_auth, agreement) -> None:
    _, header = admin_auth
    resp = await client.post(
        f"/api/v1/framework-agreements/{agreement['id']}/quote",
        json={**_ORDER, "ordered_at": "2026-04-02"},
        headers=header,
    )
    quote = resp.json()
    assert quote["blocking"] and quote["lines"] == []
    assert "FWK_ESCALATION_UNRESOLVED" in {f["code"] for f in quote["findings"]}


@pytest.mark.asyncio
async def test_issue_measure_and_roll_up(client: AsyncClient, admin_auth, agreement) -> None:
    _, header = admin_auth
    resp = await client.post(
        f"/api/v1/framework-agreements/{agreement['id']}/orders", json={**_ORDER, "issue": True}, headers=header
    )
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["order_status"] == "issued" and order["net"] == "5889.56"
    assert all(ln["origin"] == "framework_item" for ln in order["lines"])
    assert order["lines"][0]["rate_build"]["escalated_rate"] == "1923.44"
    trench = next(ln for ln in order["lines"] if ln["code"] == "01.020")
    measured = await client.post(
        f"/api/v1/framework-agreements/orders/{order['id']}/measurements",
        json={"measurements": {trench["id"]: "16.5"}},
        headers=header,
    )
    assert measured.status_code == 200, measured.text
    detail = measured.json()
    assert detail["order_status"] == "measured" and detail["measured_over_ordered"]
    assert "FWK_MEASURED_OVER_ORDERED" in {f["code"] for f in detail["findings"]}

    got = (await client.get(f"/api/v1/framework-agreements/{agreement['id']}", headers=header)).json()
    assert got["consumption"]["committed"] == "5889.56"
    assert got["consumption"]["pct"] == "84.14"
    listed = (await client.get(f"/api/v1/framework-agreements/{agreement['id']}/orders", headers=header)).json()
    assert listed["total"] == 1 and listed["items"][0]["site_label"] == "Hauptstr. 12"
    by_item = (
        await client.get(f"/api/v1/framework-agreements/{agreement['id']}/breakdown?by=item", headers=header)
    ).json()
    assert {r["label"].split()[0] for r in by_item["rows"]} == {"01.010", "01.020", "01.030"}


@pytest.mark.asyncio
async def test_over_cap_needs_a_reason_and_is_recorded(client: AsyncClient, admin_auth, agreement) -> None:
    _, header = admin_auth
    url = f"/api/v1/framework-agreements/{agreement['id']}/orders"
    no_reason = await client.post(url, json={**_ORDER, "issue": True}, headers=header)
    assert no_reason.status_code == 422, no_reason.text
    assert no_reason.json()["detail"]["error"] == "override_reason_required"
    ok = await client.post(
        url,
        json={**_ORDER, "issue": True, "override_reason": "Emergency gas leak repair ordered by the client"},
        headers=header,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["terms"]["cap_override"]["overrun"] == "4779.12"
    got = (await client.get(f"/api/v1/framework-agreements/{agreement['id']}", headers=header)).json()
    assert got["status"] == "exhausted"


@pytest.mark.asyncio
async def test_claims_go_on_orders_not_on_the_agreement(client: AsyncClient, admin_auth, agreement) -> None:
    _, header = admin_auth
    resp = await client.post(
        "/api/v1/contracts/progress-claims/",
        json={"contract_id": agreement["id"], "period_start": "2026-03-01", "period_end": "2026-03-31"},
        headers=header,
    )
    assert resp.status_code == 422, resp.text
    assert "call-off orders" in resp.text


@pytest.mark.asyncio
async def test_duplicate_codes_are_refused_on_import(client: AsyncClient, admin_auth, agreement) -> None:
    _, header = admin_auth
    resp = await client.post(
        f"/api/v1/framework-agreements/{agreement['id']}/items/import",
        json={"items": [{"code": "02.010", "base_rate": "1"}, {"code": "02.010", "base_rate": "2"}]},
        headers=header,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["codes"] == ["02.010"]


@pytest.mark.asyncio
async def test_child_lists_are_paged_and_closed_to_other_projects(client: AsyncClient, admin_auth, agreement) -> None:
    from tests.modules.framework_agreements.conftest import _register_user

    _, header = admin_auth
    base = f"/api/v1/framework-agreements/{agreement['id']}"
    for child in ("items", "periods", "adjustments"):
        page = (await client.get(f"{base}/{child}", headers=header)).json()
        assert page["total"] == len(page["items"]) and page["offset"] == 0, child
    order = (await client.post(f"{base}/orders", json=_ORDER, headers=header)).json()
    extras = (await client.get(f"/api/v1/framework-agreements/orders/{order['id']}/extras", headers=header)).json()
    assert extras["total"] == len(extras["items"])

    _, _email, stranger = await _register_user(client, role="editor")
    for path in (base, f"{base}/items", f"{base}/periods", f"/api/v1/framework-agreements/orders/{order['id']}"):
        resp = await client.get(path, headers=stranger)
        assert resp.status_code in (403, 404), (path, resp.status_code)
    listed = (await client.get("/api/v1/framework-agreements/", headers=stranger)).json()
    assert agreement["id"] not in {row["id"] for row in listed["items"]}
