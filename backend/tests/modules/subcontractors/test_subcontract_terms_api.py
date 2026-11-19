"""Levies, payment discount and the bidder radius search through the API.

Worked example 1 of the subcontractor award domain, end to end: contract sum
400,008.60, levies 0.3 + 0.5 + 0.4 %, retention 10 % capped at 5 %, invoice
120,000.00 paid within 14 days at 2 % -> 104,569.92.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor
from app.modules.subcontractors.permissions import register_subcontractors_permissions
from app.modules.subcontractors.router import router as subs_router
from app.modules.subcontractors.terms_service import SubcontractTermsService, set_subcontract_terms
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

TERMS = {
    "deduction_order": "levies_then_retention",
    "retention_cap_percent": "5",
    "payment_discount_percent": "2",
    "payment_discount_days": 14,
    "payment_discount_agreed": True,
    "levies": [
        {"code": "insurance", "name": "Construction insurance", "rate_percent": "0.3"},
        {"code": "cleaning", "name": "Site cleaning", "rate_percent": "0.5"},
        {"code": "power", "name": "Site power and water", "rate_percent": "0.4"},
    ],
}


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _seed(session, *, country: str = "DE") -> tuple[str, uuid.UUID, SubcontractAgreement]:
    from app.modules.projects.models import Project

    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Levy probe", owner_id=user.id, currency="EUR", country_code=country)
    session.add(project)
    sub = Subcontractor(legal_name=f"Drywall {uuid.uuid4().hex[:6]}", trade_categories=["drywall"])
    session.add(sub)
    await session.flush()
    agreement = SubcontractAgreement(
        id=uuid.uuid4(),
        subcontractor_id=sub.id,
        project_id=project.id,
        title="Drywall subcontract",
        currency="EUR",
        total_value=Decimal("400008.60"),
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(agreement)
    await session.flush()
    return str(user.id), project.id, agreement


def _app(db_session, caller_id: str) -> FastAPI:
    register_subcontractors_permissions()
    app = FastAPI()
    app.include_router(subs_router, prefix="/v1/subcontractors")

    async def _session_override():
        yield db_session

    async def _user() -> str:
        return caller_id

    async def _payload() -> dict:
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_worked_example_statement_through_the_api(db_session) -> None:
    caller, _project_id, agreement = await _seed(db_session)
    async with _client(_app(db_session, caller)) as client:
        put = await client.put(f"/v1/subcontractors/agreements/{agreement.id}/terms", json=TERMS)
        assert put.status_code == 200, put.text
        assert [lv["code"] for lv in put.json()["levies"]] == ["insurance", "cleaning", "power"]

        r = await client.get(
            f"/v1/subcontractors/agreements/{agreement.id}/deductions",
            params={"work_value": "120000.00", "invoice_date": "2026-03-02", "paid_on": "2026-03-16"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["levies_total"]) == Decimal("1440.00")
    assert Decimal(body["retention_amount"]) == Decimal("11856.00")
    assert Decimal(body["retention_cap_amount"]) == Decimal("20000.43")
    assert Decimal(body["payable"]) == Decimal("106704.00")
    assert Decimal(body["payment_discount_amount"]) == Decimal("2134.08")
    assert Decimal(body["amount_to_pay"]) == Decimal("104569.92")
    assert body["discount_due_date"] == "2026-03-16"
    results = {row["rule_id"]: row for row in body["validation"]}
    assert results["subcontract.levies_reconcile"]["passed"] is True
    assert results["subcontract.payment_discount_reconciles"]["passed"] is True


async def test_award_entry_point_stores_terms_on_the_contract_and_the_agreement_finds_them(db_session) -> None:
    _caller, _project_id, agreement = await _seed(db_session)
    contract_id = uuid.uuid4()
    await set_subcontract_terms(db_session, contract_id=contract_id, terms=TERMS, source="award")
    agreement.contract_id = contract_id
    await db_session.flush()

    terms = await SubcontractTermsService(db_session).get_terms(agreement.id)
    assert terms.source == "award"
    assert terms.payment_discount_percent == Decimal("2.000")
    assert len(terms.levies) == 3

    # A second call replaces, never duplicates.
    again = await set_subcontract_terms(
        db_session, agreement_id=agreement.id, terms={**TERMS, "levies": TERMS["levies"][:1]}, source="award"
    )
    assert again.contract_id == contract_id
    assert len(again.levies) == 1


async def test_bidder_search_radius_favourites_and_blocked(db_session) -> None:
    from app.modules.geo_hub.models import GeoAnchor

    caller, project_id, _agreement = await _seed(db_session)
    # Site in Hamburg; Lueneburg is about 45 km away, Hanover about 130 km.
    db_session.add(GeoAnchor(project_id=project_id, lat=Decimal("53.5511"), lon=Decimal("9.9937")))
    near = Subcontractor(legal_name="Near Trockenbau", trade_categories=["drywall"])
    far = Subcontractor(legal_name="Far Trockenbau", trade_categories=["drywall"])
    blind = Subcontractor(legal_name="No Address Trockenbau", trade_categories=["drywall"])
    blocked = Subcontractor(legal_name="Blocked Trockenbau", trade_categories=["drywall"], is_blocked=True)
    db_session.add_all([near, far, blind, blocked])
    await db_session.flush()
    svc = SubcontractTermsService(db_session)
    await svc.set_location(near.id, Decimal("53.2464"), Decimal("10.4115"))
    await svc.set_location(far.id, Decimal("52.3759"), Decimal("9.7320"))
    await svc.add_favourite(blind.id, "drywall", caller)

    async with _client(_app(db_session, caller)) as client:
        r = await client.get(
            "/v1/subcontractors/bidder-search",
            params={"project_id": str(project_id), "trade": "drywall", "radius_km": "50"},
        )
        wide = await client.get(
            "/v1/subcontractors/bidder-search",
            params={"project_id": str(project_id), "trade": "drywall", "radius_km": "50", "include_outside": True},
        )
    assert r.status_code == 200, r.text
    names = [row["legal_name"] for row in r.json()["items"]]
    assert "Blocked Trockenbau" not in names
    assert "Far Trockenbau" not in names
    # Favourite first even without coordinates, then the nearest.
    assert names[0] == "No Address Trockenbau"
    assert "Near Trockenbau" in names
    near_row = next(row for row in r.json()["items"] if row["legal_name"] == "Near Trockenbau")
    assert 40 < float(near_row["distance_km"]) < 50
    assert r.json()["site_has_coordinates"] is True
    assert r.json()["hidden_blocked"] >= 1

    wide_body = wide.json()
    assert "Far Trockenbau" in [row["legal_name"] for row in wide_body["items"]]
    findings = [v for v in wide_body["validation"] if v["rule_id"] == "tender.recipient_outside_radius"]
    assert findings and findings[0]["element_ref"] == "Far Trockenbau"
    assert findings[0]["severity"] == "info"


async def test_geocode_without_address_says_so(db_session) -> None:
    caller, _project_id, agreement = await _seed(db_session)
    async with _client(_app(db_session, caller)) as client:
        r = await client.post(f"/v1/subcontractors/subcontractors/{agreement.subcontractor_id}/geocode")
    assert r.status_code == 200, r.text
    assert r.json() == {**r.json(), "has_coordinates": False, "reason": "no_address"}


async def test_levy_catalogue_crud_and_duplicate_code(db_session) -> None:
    caller, _project_id, _agreement = await _seed(db_session)
    item = {"code": "insurance", "name": "Construction insurance", "default_percent": "0.3"}
    async with _client(_app(db_session, caller)) as client:
        created = await client.post("/v1/subcontractors/levy-catalogue", json=item)
        dup = await client.post("/v1/subcontractors/levy-catalogue", json=item)
        listed = await client.get("/v1/subcontractors/levy-catalogue")
    assert created.status_code == 201, created.text
    assert dup.status_code == 409
    assert [i["code"] for i in listed.json()["items"]] == ["insurance"]
