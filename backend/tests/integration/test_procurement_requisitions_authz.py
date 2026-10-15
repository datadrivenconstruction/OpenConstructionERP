# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Material requisitions over HTTP: lifecycle, provenance, validation and access.

Drives ``/api/v1/procurement/requisitions`` against the real app and the test
PostgreSQL. The bill the requisitions are raised from is written straight to
the database, two positions using the same concrete so the buy list folds them
into one row, and the requisition raised from that row keeps both sources.

The ``authz`` in the file name puts it in the PR-gating tenant isolation lane,
the same as ``test_procurement_authz.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.costmodel.models  # noqa: F401
import app.modules.procurement.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401

BASE = "/api/v1/procurement/requisitions"
DENIED = (403, 404)


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_login(client: AsyncClient, *, tenant: str, role: str | None = None) -> dict:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@req-authz.io"
    password = f"ReqAuthz{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    values: dict = {"is_active": True}
    if role is not None:
        values["role"] = role
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(**values))
        await s.commit()

    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"user_id": reg.json()["id"], "headers": {"Authorization": f"Bearer {login.json()['access_token']}"}}


@pytest_asyncio.fixture(scope="module")
async def owner(http_client):
    return await _register_login(http_client, tenant="req-owner", role="admin")


@pytest_asyncio.fixture(scope="module")
async def outsider(http_client):
    # An editor holds procurement.create/update, so only the project gate stops them.
    return await _register_login(http_client, tenant="req-outsider", role="editor")


async def _seed_bill(project_id: str) -> dict:
    """Two positions using the same concrete; the first is on the cost spine."""
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position
    from app.modules.costmodel.models import CostLine

    pid = uuid.UUID(project_id)
    async with async_session_factory() as s:
        boq = BOQ(project_id=pid, name="Bill", description="")
        s.add(boq)
        await s.flush()
        positions = []
        for ordinal, qty in (("1.1", "50"), ("1.2", "20")):
            pos = Position(
                boq_id=boq.id,
                ordinal=ordinal,
                description=f"Wall {ordinal}",
                unit="m3",
                quantity=qty,
                unit_rate="100",
                total="0",
                metadata_={
                    "resources": [
                        {
                            "type": "material",
                            "name": "Concrete C30/37",
                            "unit": "m3",
                            "quantity": "1.02",
                            "code": "C30",
                        },
                        {"type": "labor", "name": "Mason", "unit": "h", "quantity": "3.5"},
                    ]
                },
            )
            s.add(pos)
            positions.append(pos)
        await s.flush()
        cost_line = CostLine(
            project_id=pid,
            code="CL-1.1",
            description="Wall 1.1",
            unit="m3",
            source="boq",
            boq_position_id=positions[0].id,
            boq_id=boq.id,
            estimate_quantity="50",
            estimate_unit_rate="100",
            estimate_amount="5000",
            currency="",
            status="active",
        )
        s.add(cost_line)
        await s.flush()
        positions[0].cost_line_id = cost_line.id
        await s.commit()
        return {"positions": [str(p.id) for p in positions], "cost_line_id": str(cost_line.id)}


@pytest_asyncio.fixture(scope="module")
async def project(http_client, owner):
    resp = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"ReqProj {uuid.uuid4().hex[:6]}",
            "description": "Requisition API",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=owner["headers"],
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]
    bill = await _seed_bill(project_id)
    return {"id": project_id, **bill}


def _future(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


async def _buy_list_row(http_client, owner, project) -> dict:
    resp = await http_client.get(
        f"/api/v1/resource-summary/projects/{project['id']}/buy-list",
        headers=owner["headers"],
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert len(rows) == 1
    return rows[0]


async def _create_from_row(http_client, owner, project, row: dict, **overrides) -> dict:
    body = {
        "project_id": project["id"],
        "title": "Concrete for walls",
        "required_date": _future(),
        "items": [
            {
                "description": row["name"],
                "unit": row["unit"],
                "quantity_requested": row["quantity"],
                "sources": [
                    {
                        "boq_position_id": s["position_id"],
                        "resource_key": s["resource_key"],
                        "quantity": s["quantity"],
                        "unit": s["unit"],
                    }
                    for s in row["sources"]
                ],
            }
        ],
    }
    body.update(overrides)
    resp = await http_client.post(f"{BASE}/", json=body, headers=owner["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Buy list sources ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_list_row_names_every_contributing_source(http_client, owner, project):
    row = await _buy_list_row(http_client, owner, project)
    # The existing fields are unchanged.
    assert row["name"] == "Concrete C30/37"
    assert row["unit"] == "m3"
    assert row["quantity"] == "71.4000"
    assert row["position_count"] == 2
    # And each position's contribution is named, not only counted.
    by_position = {s["position_id"]: s for s in row["sources"]}
    assert set(by_position) == set(project["positions"])
    assert by_position[project["positions"][0]]["quantity"] == "51.0000"
    assert by_position[project["positions"][1]]["quantity"] == "20.4000"
    assert all(s["resource_key"] == "0:C30" and s["unit"] == "m3" for s in row["sources"])


# ── Lifecycle ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_requisition_lifecycle_keeps_provenance_and_never_auto_approves(http_client, owner, project):
    row = await _buy_list_row(http_client, owner, project)
    created = await _create_from_row(http_client, owner, project, row)

    assert created["status"] == "draft"
    assert created["req_number"].startswith("MR-")
    assert created["requester_id"] == owner["user_id"]
    [line] = created["items"]
    assert line["quantity_requested"] == "71.4000"
    sources = {s["boq_position_id"]: s for s in line["sources"]}
    assert set(sources) == set(project["positions"])
    # The source on the spine carries its cost line; the other does not invent one.
    assert sources[project["positions"][0]]["cost_line_id"] == project["cost_line_id"]
    assert sources[project["positions"][1]]["cost_line_id"] is None
    assert sources[project["positions"][0]]["quantity"] == "51.0000"
    assert line["quantity_outstanding"] == "71.4000"
    assert created["reconciliation"]["outstanding"] == "71.4000"

    req_id = created["id"]
    got = await http_client.get(f"{BASE}/{req_id}", headers=owner["headers"])
    assert got.status_code == 200
    assert {s["boq_position_id"] for s in got.json()["items"][0]["sources"]} == set(project["positions"])

    patched = await http_client.patch(
        f"{BASE}/{req_id}", json={"title": "Concrete, walls L1"}, headers=owner["headers"]
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "Concrete, walls L1"
    # A header edit leaves the lines and their sources alone.
    assert len(patched.json()["items"][0]["sources"]) == 2

    submitted = await http_client.post(f"{BASE}/{req_id}/submit", headers=owner["headers"])
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["approver_id"] is None

    # Submitting again is a no-op, not a second history entry.
    again = await http_client.post(f"{BASE}/{req_id}/submit", headers=owner["headers"])
    assert again.status_code == 200
    assert [h["action"] for h in again.json()["history"]].count("submitted") == 1

    # Only a draft can be edited.
    locked = await http_client.patch(f"{BASE}/{req_id}", json={"title": "late"}, headers=owner["headers"])
    assert locked.status_code == 409

    listed = await http_client.get(
        f"{BASE}/", params={"project_id": project["id"], "status": "submitted"}, headers=owner["headers"]
    )
    assert listed.status_code == 200
    assert req_id in {r["id"] for r in listed.json()["items"]}
    drafts = await http_client.get(
        f"{BASE}/", params={"project_id": project["id"], "status": "draft"}, headers=owner["headers"]
    )
    assert req_id not in {r["id"] for r in drafts.json()["items"]}

    withdrawn = await http_client.post(f"{BASE}/{req_id}/withdraw", headers=owner["headers"])
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "draft"

    cancelled = await http_client.post(
        f"{BASE}/{req_id}/cancel", json={"reason": "design changed"}, headers=owner["headers"]
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert [h["action"] for h in body["history"]] == ["created", "updated", "submitted", "withdrawn", "cancelled"]
    assert body["history"][-1]["reason"] == "design changed"

    # Cancelled is terminal.
    reopened = await http_client.post(f"{BASE}/{req_id}/submit", headers=owner["headers"])
    assert reopened.status_code == 409


@pytest.mark.asyncio
async def test_lines_merge_only_on_the_same_catalogue_item(http_client, owner, project):
    catalog_item = str(uuid.uuid4())
    resp = await http_client.post(
        f"{BASE}/",
        json={
            "project_id": project["id"],
            "items": [
                {
                    "description": "Rebar B500 12mm",
                    "unit": "t",
                    "quantity_requested": "2",
                    "catalog_item_id": catalog_item,
                },
                {
                    "description": "Rebar B500 12",
                    "unit": "t",
                    "quantity_requested": "1.5",
                    "catalog_item_id": catalog_item,
                },
                {"description": "Sand", "unit": "t", "quantity_requested": "4"},
                {"description": "Sand", "unit": "t", "quantity_requested": "6"},
            ],
        },
        headers=owner["headers"],
    )
    assert resp.status_code == 201, resp.text
    lines = resp.json()["items"]
    # The coded pair merged; the two uncoded "Sand" lines stay apart for a person to decide.
    assert [(line["description"], line["quantity_requested"]) for line in lines] == [
        ("Rebar B500 12mm", "3.5"),
        ("Sand", "4"),
        ("Sand", "6"),
    ]


@pytest.mark.asyncio
async def test_status_filter_rejects_unknown_status(http_client, owner, project):
    resp = await http_client.get(
        f"{BASE}/", params={"project_id": project["id"], "status": "bogus"}, headers=owner["headers"]
    )
    assert resp.status_code == 422


# ── Validation blocks submission ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "rule_id"),
    [
        ({"quantity_requested": "0"}, "procurement.requisition_quantity_positive"),
        ({"unit": "t"}, "procurement.requisition_source_unit"),
        (
            {"required_date": (date.today() - timedelta(days=1)).isoformat()},
            "procurement.requisition_needed_by_not_past",
        ),
    ],
)
async def test_submit_is_refused_by_the_requisition_rules(http_client, owner, project, overrides, rule_id):
    row = await _buy_list_row(http_client, owner, project)
    required = overrides.pop("required_date", _future())
    created = await _create_from_row(http_client, owner, project, row, required_date=required)
    if overrides:
        item = {
            "description": row["name"],
            "unit": overrides.get("unit", row["unit"]),
            "quantity_requested": overrides.get("quantity_requested", row["quantity"]),
            "sources": [
                {
                    "boq_position_id": s["position_id"],
                    "resource_key": s["resource_key"],
                    "quantity": s["quantity"],
                    "unit": s["unit"],
                }
                for s in row["sources"]
            ],
        }
        patched = await http_client.patch(f"{BASE}/{created['id']}", json={"items": [item]}, headers=owner["headers"])
        assert patched.status_code == 200, patched.text

    report = await http_client.get(f"{BASE}/{created['id']}/validate", headers=owner["headers"])
    assert report.status_code == 200
    failing = {r["rule_id"] for r in report.json()["results"] if not r["passed"]}
    assert rule_id in failing

    resp = await http_client.post(f"{BASE}/{created['id']}/submit", headers=owner["headers"])
    assert resp.status_code == 422, resp.text
    assert rule_id in {e["rule_id"] for e in resp.json()["detail"]["errors"]}
    still = await http_client.get(f"{BASE}/{created['id']}", headers=owner["headers"])
    assert still.json()["status"] == "draft"


# ── Access ──────────────────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_outsider_cannot_reach_another_projects_requisition(http_client, owner, outsider, project):
    row = await _buy_list_row(http_client, owner, project)
    created = await _create_from_row(http_client, owner, project, row)
    rid = created["id"]
    h = outsider["headers"]

    assert (await http_client.get(f"{BASE}/{rid}", headers=h)).status_code in DENIED
    assert (await http_client.get(f"{BASE}/", params={"project_id": project["id"]}, headers=h)).status_code in DENIED
    assert (await http_client.patch(f"{BASE}/{rid}", json={"title": "x"}, headers=h)).status_code in DENIED
    assert (await http_client.post(f"{BASE}/{rid}/submit", headers=h)).status_code in DENIED
    assert (await http_client.post(f"{BASE}/{rid}/cancel", headers=h)).status_code in DENIED
    create = await http_client.post(f"{BASE}/", json={"project_id": project["id"], "items": []}, headers=h)
    assert create.status_code in DENIED

    after = await http_client.get(f"{BASE}/{rid}", headers=owner["headers"])
    assert after.json()["status"] == "draft"
    assert after.json()["title"] == "Concrete for walls"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_a_source_position_from_another_project_is_refused(http_client, owner, project):
    other = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Other {uuid.uuid4().hex[:6]}", "region": "DACH", "currency": "EUR"},
        headers=owner["headers"],
    )
    assert other.status_code == 201, other.text
    resp = await http_client.post(
        f"{BASE}/",
        json={
            "project_id": other.json()["id"],
            "items": [
                {
                    "description": "Concrete",
                    "unit": "m3",
                    "quantity_requested": "1",
                    "sources": [{"boq_position_id": project["positions"][0], "quantity": "1", "unit": "m3"}],
                }
            ],
        },
        headers=owner["headers"],
    )
    assert resp.status_code == 404, resp.text


# ── Existing readers of the requisition tables ──────────────────────────────


@pytest.mark.asyncio
async def test_site_inventory_and_bi_still_read_requisition_lines(http_client, owner, project):
    row = await _buy_list_row(http_client, owner, project)
    created = await _create_from_row(http_client, owner, project, row)
    item_id = created["items"][0]["id"]

    from app.database import async_session_factory
    from app.modules.bi_dashboards.kpis import procurement_savings_kpi
    from app.modules.site_inventory.service import SiteInventoryService

    async with async_session_factory() as s:
        svc = SiteInventoryService(s)
        pid = uuid.UUID(project["id"])
        await svc._require_req_item_in_project(pid, uuid.UUID(item_id))
        refs = await svc._ordered_refs(pid, [item_id])
        assert refs[item_id].unit == "m3"
        result = await procurement_savings_kpi(s, project_id=pid)
        assert result is not None
