# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing API on real PostgreSQL: lifecycle, idempotent schedule, finance invoices, arrears, guards."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.contacts.models import Contact
from app.modules.finance.models import Invoice, Payment
from app.modules.leasing.router import router as leasing_router
from app.modules.leasing.validators import register_leasing_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_leasing_validation_rules()
    async with transactional_session() as s:
        yield s


async def _user(session, role: str = "editor") -> uuid.UUID:
    u = User(email=f"lease-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role=role)
    session.add(u)
    await session.flush()
    return u.id


async def _project(session, owner_id: uuid.UUID) -> uuid.UUID:
    p = Project(name="Lease test", owner_id=owner_id, currency="EUR")
    session.add(p)
    await session.flush()
    return p.id


async def _tenant(session) -> str:
    c = Contact(contact_type="client", company_name="Tenant Ltd")
    session.add(c)
    await session.flush()
    return str(c.id)


def _app(session, caller: uuid.UUID, role: str = "admin", permissions: list[str] | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(leasing_router, prefix="/v1/leasing")

    async def _session():
        yield session

    async def _uid() -> str:
        return str(caller)

    async def _payload() -> dict:
        return {"sub": str(caller), "role": role, "permissions": permissions or []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _uid
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _body(project_id, tenant, **kw) -> dict:
    base = {
        "project_id": str(project_id),
        "code": "L-001",
        "unit_kind": "plot",
        "unit_ref": "plot-7",
        "unit_label": "Unit 7",
        "tenant_contact_id": tenant,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "rent_amount": "1500.00",
        "currency": "EUR",
        "frequency": "monthly",
        "deposit": "3000.00",
        "escalation_kind": "fixed",
        "escalation_rate": "2.5",
        "tax_rate": "0",
    }
    base.update(kw)
    return base


async def _setup(session):
    owner = await _user(session, role="admin")
    project = await _project(session, owner)
    tenant = await _tenant(session)
    await session.commit()
    return owner, project, tenant


async def test_lifecycle_schedule_invoices_and_arrears(db_session):
    owner, project, tenant = await _setup(db_session)
    async with _http(_app(db_session, owner)) as c:
        r = await c.post("/v1/leasing/", json=_body(project, tenant))
        assert r.status_code == 201, r.text
        lease = r.json()
        lease_id = lease["id"]
        assert lease["status"] == "draft"
        assert lease["term_months"] == 12
        assert lease["rent_amount"] == "1500.00"

        r = await c.post(f"/v1/leasing/{lease_id}/activate", json={})
        assert r.status_code == 200, r.text
        sched = (await c.get(f"/v1/leasing/{lease_id}/schedule")).json()
        assert len(sched["items"]) == 12
        assert sched["total"] == "18000.00"

        again = (await c.post(f"/v1/leasing/{lease_id}/schedule")).json()
        assert [x["id"] for x in again["items"]] == [x["id"] for x in sched["items"]]

        run = {"project_id": str(project), "as_of": "2026-02-15"}
        r = await c.post("/v1/leasing/schedule/run", json=run)
        assert r.status_code == 200, r.text
        assert r.json()["invoices_created"] == 2
        r = await c.post("/v1/leasing/schedule/run", json=run)
        assert r.json()["invoices_created"] == 0

        rows = await db_session.execute(select(Invoice).where(Invoice.project_id == project))
        invoices = list(rows.scalars().all())
        assert {i.invoice_direction for i in invoices} == {"receivable"}
        assert all(i.status == "draft" for i in invoices)
        first = min(invoices, key=lambda i: i.invoice_date)
        assert Decimal(first.amount_total) == Decimal("1500.00")

        arrears = (await c.get(f"/v1/leasing/arrears?project_id={project}&as_of=2026-03-01")).json()
        assert arrears["items"] == []

        for inv in invoices:
            inv.status = "sent"
        db_session.add(
            Payment(invoice_id=first.id, payment_date="2026-01-20", amount=Decimal("500.00"), currency_code="EUR")
        )
        await db_session.flush()
        # The earlier arrears call loaded this invoice's payments into the shared session.
        await db_session.refresh(first, ["payments"])
        arrears = (await c.get(f"/v1/leasing/arrears?project_id={project}&as_of=2026-03-01")).json()
        assert sorted(x["due"] for x in arrears["items"]) == ["1000.00", "1500.00"]
        assert arrears["totals"]["EUR"]["total"] == "2500.00"

        roll = (await c.get(f"/v1/leasing/rent-roll?project_id={project}&as_of=2026-03-15")).json()
        assert roll["items"][0]["annual_rent"] == "18000.00"

        r = await c.post(f"/v1/leasing/{lease_id}/terminate", json={"effective": "2026-06-30"})
        assert r.status_code == 200, r.text
        sched = (await c.get(f"/v1/leasing/{lease_id}/schedule")).json()
        assert len(sched["items"]) == 6

        detail = (await c.get(f"/v1/leasing/{lease_id}")).json()
        kinds = [e["kind"] for e in detail["events"]]
        assert kinds[:2] == ["created", "activated"]
        assert "termination" in kinds

        r = await c.get(f"/v1/leasing/export?project_id={project}&format=csv")
        assert r.status_code == 200
        assert r.text.startswith("code,status")
        r = await c.get(f"/v1/leasing/export?project_id={project}&format=nope")
        assert r.status_code == 422


async def test_overlap_end_before_start_and_negative_deposit_refused(db_session):
    owner, project, tenant = await _setup(db_session)
    async with _http(_app(db_session, owner)) as c:
        first = (await c.post("/v1/leasing/", json=_body(project, tenant))).json()
        assert (await c.post(f"/v1/leasing/{first['id']}/activate", json={})).status_code == 200

        second = await c.post("/v1/leasing/", json=_body(project, tenant, code="L-002", start_date="2026-06-01"))
        assert second.status_code == 422
        assert any(e["rule_id"] == "leasing.no_overlap" for e in second.json()["detail"]["validation"])

        r = await c.post("/v1/leasing/", json=_body(project, tenant, code="L-003", unit_ref="x", end_date="2025-01-01"))
        assert r.status_code == 422
        r = await c.post("/v1/leasing/", json=_body(project, tenant, code="L-004", unit_ref="y", deposit="-1"))
        assert r.status_code == 422

        r = await c.patch(f"/v1/leasing/{first['id']}", json={"rent_amount": "1"})
        assert r.status_code == 409


async def test_renewal_follows_on_and_live_lease_cannot_be_deleted(db_session):
    owner, project, tenant = await _setup(db_session)
    async with _http(_app(db_session, owner)) as c:
        lease = (await c.post("/v1/leasing/", json=_body(project, tenant))).json()
        await c.post(f"/v1/leasing/{lease['id']}/activate", json={})
        r = await c.post(f"/v1/leasing/{lease['id']}/renew", json={"end_date": "2027-12-31", "rent_amount": "1600"})
        assert r.status_code == 201, r.text
        assert r.json()["start_date"] == "2027-01-01"
        assert r.json()["renewed_from_id"] == lease["id"]
        assert (await c.delete(f"/v1/leasing/{lease['id']}")).status_code == 409
        assert (await c.delete(f"/v1/leasing/{r.json()['id']}")).status_code == 204


@pytest.mark.tenant_isolation
async def test_other_users_lease_is_404(db_session):
    owner, project, tenant = await _setup(db_session)
    stranger = await _user(db_session)
    await db_session.commit()
    async with _http(_app(db_session, owner)) as c:
        lease = (await c.post("/v1/leasing/", json=_body(project, tenant))).json()
    perms = ["leasing.read", "leasing.update", "leasing.manage", "leasing.bill", "leasing.delete"]
    async with _http(_app(db_session, stranger, role="editor", permissions=perms)) as c:
        assert (await c.get(f"/v1/leasing/{lease['id']}")).status_code == 404
        assert (await c.get(f"/v1/leasing/{lease['id']}/schedule")).status_code == 404
        assert (await c.post(f"/v1/leasing/{lease['id']}/activate", json={})).status_code == 404
        assert (await c.get(f"/v1/leasing/?project_id={project}")).status_code == 404
        assert (await c.get(f"/v1/leasing/arrears?project_id={project}")).status_code == 404
        r = await c.post("/v1/leasing/schedule/run", json={"project_id": str(project)})
        assert r.status_code == 404


async def test_viewer_cannot_create(db_session):
    owner = await _user(db_session, role="viewer")
    project = await _project(db_session, owner)
    tenant = await _tenant(db_session)
    await db_session.commit()
    async with _http(_app(db_session, owner, role="viewer", permissions=["leasing.read"])) as c:
        r = await c.post("/v1/leasing/", json=_body(project, tenant))
    assert r.status_code == 403
