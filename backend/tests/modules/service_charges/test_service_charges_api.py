# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges API on real PostgreSQL: keys, budget approval, idempotent demands, reconciliation, guards."""

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
from app.modules.finance.models import Invoice, InvoiceLineItem
from app.modules.projects.models import Project
from app.modules.service_charges.router import router as sc_router
from app.modules.service_charges.validators import register_service_charges_validation_rules
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_service_charges_validation_rules()
    async with transactional_session() as s:
        yield s


async def _user(session, role: str = "editor") -> uuid.UUID:
    u = User(email=f"svc-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role=role)
    session.add(u)
    await session.flush()
    return u.id


async def _project(session, owner_id: uuid.UUID) -> uuid.UUID:
    p = Project(name="Service charge test", owner_id=owner_id, currency="EUR")
    session.add(p)
    await session.flush()
    return p.id


async def _owner(session, name: str) -> str:
    c = Contact(contact_type="client", company_name=name)
    session.add(c)
    await session.flush()
    return str(c.id)


def _app(session, caller: uuid.UUID, role: str = "admin") -> FastAPI:
    app = FastAPI()
    app.include_router(sc_router, prefix="/v1/service-charges")

    async def _session():
        yield session

    async def _uid() -> str:
        return str(caller)

    async def _payload() -> dict:
        return {"sub": str(caller), "role": role, "permissions": []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _uid
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _setup(session, client: AsyncClient, project_id: uuid.UUID) -> tuple[str, str]:
    a = await client.post(
        "/v1/service-charges/",
        json={"project_id": str(project_id), "name": "Block A owners", "currency": "EUR"},
    )
    assert a.status_code == 201, a.text
    assoc = a.json()["id"]
    owners = [await _owner(session, f"Owner {i}") for i in range(3)]
    k = await client.post(
        f"/v1/service-charges/{assoc}/keys",
        json={
            "name": "Permille",
            "method": "permille",
            "lines": [
                {"unit_ref": "U1", "share": "333.333", "payer_contact_id": owners[0]},
                {"unit_ref": "U2", "share": "333.333", "payer_contact_id": owners[1]},
                {"unit_ref": "U3", "share": "333.334", "payer_contact_id": owners[2]},
            ],
        },
    )
    assert k.status_code == 201, k.text
    return assoc, k.json()["id"]


async def test_key_shares_must_add_up_exactly(db_session) -> None:
    uid = await _user(db_session)
    pid = await _project(db_session, uid)
    async with _http(_app(db_session, uid)) as client:
        a = await client.post("/v1/service-charges/", json={"project_id": str(pid), "name": "X", "currency": "EUR"})
        r = await client.post(
            f"/v1/service-charges/{a.json()['id']}/keys",
            json={"name": "Bad", "method": "permille", "lines": [{"unit_ref": "U1", "share": "999.999"}]},
        )
        assert r.status_code == 422
        assert r.json()["detail"]["validation"][0]["rule_id"] == "service_charges.key_shares_total"


async def test_budget_demands_and_reconciliation(db_session) -> None:
    uid = await _user(db_session)
    pid = await _project(db_session, uid)
    async with _http(_app(db_session, uid)) as client:
        assoc, key = await _setup(db_session, client, pid)
        b = await client.post(
            f"/v1/service-charges/{assoc}/budgets",
            json={
                "year": 2025,
                "demand_frequency": "quarterly",
                "lines": [{"category": "cleaning", "amount": "1000.00", "key_id": key}],
            },
        )
        assert b.status_code == 201, b.text
        budget = b.json()["id"]
        assert b.json()["total"] == "1000.00"

        dup = await client.post(f"/v1/service-charges/{assoc}/budgets", json={"year": 2025})
        assert dup.status_code == 409

        early = await client.post("/v1/service-charges/demands/run", json={"budget_id": budget, "period": 1})
        assert early.status_code == 422
        assert early.json()["detail"]["validation"][0]["rule_id"] == "service_charges.demand_needs_approved_budget"

        ap = await client.post(f"/v1/service-charges/budgets/{budget}/approve")
        assert ap.status_code == 200 and ap.json()["status"] == "approved"

        units = (await client.get(f"/v1/service-charges/budgets/{budget}/units")).json()
        assert sum(Decimal(u["yearly"]) for u in units["units"]) == Decimal("1000.00")

        run = await client.post("/v1/service-charges/demands/run", json={"budget_id": budget, "period": 1})
        assert run.status_code == 200, run.text
        assert run.json()["created"] == 3
        again = await client.post("/v1/service-charges/demands/run", json={"budget_id": budget, "period": 1})
        assert again.json() == {"period": 1, "created": 0, "skipped": 3, "invoice_ids": []}

        for period in (2, 3, 4):
            r = await client.post("/v1/service-charges/demands/run", json={"budget_id": budget, "period": period})
            assert r.status_code == 200, r.text
        demands = (await client.get(f"/v1/service-charges/budgets/{budget}/demands")).json()
        assert len(demands) == 12
        # Instalments of each unit add up to its yearly share, so the year adds up to the budget exactly.
        assert sum(Decimal(d["amount"]) for d in demands) == Decimal("1000.00")
        inv_ids = [uuid.UUID(d["invoice_id"]) for d in demands]
        invs = (await db_session.execute(select(Invoice).where(Invoice.id.in_(inv_ids)))).scalars().all()
        assert {i.invoice_direction for i in invs} == {"receivable"}
        assert all(isinstance(i.amount_total, Decimal) for i in invs)

        payable = Invoice(
            project_id=pid,
            invoice_direction="payable",
            invoice_number=f"P-{uuid.uuid4().hex[:6]}",
            invoice_date="2025-06-01",
            currency_code="EUR",
            amount_subtotal=Decimal("300.00"),
            amount_total=Decimal("300.00"),
            status="approved",
        )
        payable.line_items = [
            InvoiceLineItem(description="Cleaning", amount=Decimal("300.00"), cost_category="cleaning")
        ]
        db_session.add(payable)
        await db_session.flush()

        rec = await client.post(f"/v1/service-charges/budgets/{budget}/reconciliation/compute")
        assert rec.status_code == 200, rec.text
        body = rec.json()
        assert body["total_actual"] == "300.00"
        assert body["actual_by_category"] == {"cleaning": "300.00"}
        for row in body["unit_balances"]:
            assert Decimal(row["balance"]) == Decimal(row["demanded"]) - Decimal(row["actual_share"])

        posted = await client.post(f"/v1/service-charges/budgets/{budget}/reconciliation/post")
        assert posted.status_code == 200, posted.text
        assert posted.json()["status"] == "posted"
        assert len(posted.json()["posted_credit_ids"]) == 3 and posted.json()["posted_invoice_ids"] == []
        closed = (await client.get(f"/v1/service-charges/budgets/{budget}")).json()
        assert closed["status"] == "closed"

        csv_export = await client.get(f"/v1/service-charges/{assoc}/export?format=csv")
        assert csv_export.status_code == 200
        assert csv_export.text.splitlines()[0].startswith("association,year,period")


async def test_other_users_project_is_hidden(db_session) -> None:
    owner = await _user(db_session)
    pid = await _project(db_session, owner)
    async with _http(_app(db_session, owner)) as client:
        assoc, _ = await _setup(db_session, client, pid)
    stranger = await _user(db_session)
    async with _http(_app(db_session, stranger, role="editor")) as client:
        r = await client.get(f"/v1/service-charges/{assoc}")
        assert r.status_code in (403, 404)
        r = await client.get(f"/v1/service-charges/?project_id={pid}")
        assert r.status_code in (403, 404)
