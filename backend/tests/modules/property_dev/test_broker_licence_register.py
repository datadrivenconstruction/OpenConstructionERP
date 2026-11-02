# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Broker licence register: neutral entity, country-driven rules, the Riyadh demo, the API.

The rules never name a country. Which authority and label a country expects, and whether the
rule is on by default, come from the regional profile; a development can override it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.core.demo_real_estate import seed_real_estate_demo
from app.core.regional_packages import broker_licence_policy
from app.core.validation.engine import ValidationContext
from app.core.validation.rules.broker_licence import (
    PropDevBrokerLicenceExpiringSoon,
    PropDevBrokerLicenceValidOnDealDate,
    licence_held_on,
)
from app.modules.projects.models import Project
from app.modules.property_dev.models import BrokerLicence, Development, SalesContract
from app.modules.users.models import User
from tests._pg import transactional_session

from .conftest import _register_user

RULES_FILE = Path(__file__).resolve().parents[3] / "app/core/validation/rules/broker_licence.py"


def _lic(status="active", authority="REGA", valid_from=None, valid_to=None):
    return SimpleNamespace(status=status, authority_code=authority, valid_from=valid_from, valid_to=valid_to)


# ── Pure window logic ───────────────────────────────────────────────────


def test_window_is_inclusive_and_open_ended_dates_do_not_limit() -> None:
    day = date(2026, 5, 1)
    assert licence_held_on([_lic(valid_from=day, valid_to=day)], day) is not None
    assert licence_held_on([_lic(valid_from=day + timedelta(days=1))], day) is None
    assert licence_held_on([_lic(valid_to=day - timedelta(days=1))], day) is None
    assert licence_held_on([_lic()], day) is not None


def test_only_active_licences_of_the_wanted_authority_count() -> None:
    day = date(2026, 5, 1)
    assert licence_held_on([_lic(status="revoked")], day) is None
    assert licence_held_on([_lic(status="suspended")], day) is None
    assert licence_held_on([_lic(authority="OTHER")], day, "rega") is None
    assert licence_held_on([_lic(authority="OTHER")], day) is not None


def test_latest_ending_licence_is_returned() -> None:
    day = date(2026, 5, 1)
    soon, late = _lic(valid_to=date(2026, 6, 1)), _lic(valid_to=date(2027, 1, 1))
    assert licence_held_on([soon, late], day) is late


# ── Country data, not core code ─────────────────────────────────────────


def test_saudi_profile_carries_the_authority_label_and_default() -> None:
    policy = broker_licence_policy("sa")
    assert policy["authority_code"] == "REGA"
    assert policy["licence_label"] == "FAL licence"
    assert policy["enabled_by_default"] is True
    assert policy["note"]


def test_countries_without_a_profile_ask_nothing() -> None:
    assert broker_licence_policy("DE") == {}
    assert broker_licence_policy(None) == {}


def test_the_core_rules_name_no_country_or_authority() -> None:
    text = RULES_FILE.read_text(encoding="utf-8")
    for needle in ("REGA", "FAL", "Saudi", '"SA"'):
        assert needle not in text, needle


# ── Rules on the Riyadh demo (PostgreSQL) ───────────────────────────────


@pytest_asyncio.fixture
async def seeded() -> AsyncIterator[tuple]:
    async with transactional_session() as session:
        user = User(email=f"bl-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        project = Project(name="Riyadh off-plan", owner_id=user.id, currency="SAR", country_code="SA")
        session.add(project)
        await session.flush()
        await seed_real_estate_demo(session, project.id, user.id, "residential-riyadh-offplan")
        dev = (await session.execute(select(Development).where(Development.project_id == project.id))).scalar_one()
        yield session, dev


def _ctx(session, dev, **extra) -> ValidationContext:
    return ValidationContext(
        data={}, project_id=str(dev.id), metadata={"session": session, "development_id": dev.id, **extra}
    )


@pytest.mark.asyncio
async def test_demo_brokers_hold_valid_licences_so_the_rule_passes(seeded) -> None:
    session, dev = seeded
    licences = (await session.execute(select(BrokerLicence))).scalars().all()
    assert len(licences) == 3
    assert all(lic.authority_code == "REGA" and lic.licence_number.startswith("DEMO-") for lic in licences)
    results = await PropDevBrokerLicenceValidOnDealDate().validate(_ctx(session, dev))
    assert results and all(r.passed for r in results)


@pytest.mark.asyncio
async def test_a_deal_outside_the_licence_window_is_an_error(seeded) -> None:
    session, dev = seeded
    for lic in (await session.execute(select(BrokerLicence))).scalars():
        lic.valid_to = date(2025, 12, 31)
    await session.flush()
    results = await PropDevBrokerLicenceValidOnDealDate().validate(_ctx(session, dev))
    failed = [r for r in results if not r.passed]
    assert failed
    assert all(r.severity.value == "error" for r in failed)
    contract_ids = {str(c) for c in (await session.execute(select(SalesContract.id))).scalars()}
    assert any(r.element_ref.split(":")[-1] in contract_ids for r in failed)
    assert "FAL licence" in failed[0].message


@pytest.mark.asyncio
async def test_a_revoked_licence_does_not_count(seeded) -> None:
    session, dev = seeded
    for lic in (await session.execute(select(BrokerLicence))).scalars():
        lic.status = "revoked"
    await session.flush()
    results = await PropDevBrokerLicenceValidOnDealDate().validate(_ctx(session, dev))
    assert any(not r.passed for r in results)


@pytest.mark.asyncio
async def test_the_rule_is_off_where_the_country_does_not_enable_it(seeded) -> None:
    session, dev = seeded
    for lic in (await session.execute(select(BrokerLicence))).scalars():
        lic.status = "revoked"
    dev.country_code = "DE"
    await session.flush()
    assert await PropDevBrokerLicenceValidOnDealDate().validate(_ctx(session, dev)) == []
    dev.metadata_ = {**(dev.metadata_ or {}), "broker_licence_required": True}
    await session.flush()
    assert any(not r.passed for r in await PropDevBrokerLicenceValidOnDealDate().validate(_ctx(session, dev)))


@pytest.mark.asyncio
async def test_licence_expiry_warns_at_30_days_and_notes_at_60(seeded) -> None:
    session, dev = seeded
    today = datetime.now(UTC).date()
    licences = list((await session.execute(select(BrokerLicence))).scalars())
    licences[0].valid_from = today - timedelta(days=400)
    licences[0].valid_to = today + timedelta(days=10)
    for lic in licences[1:]:
        lic.valid_to = today + timedelta(days=200)
    await session.flush()
    results = await PropDevBrokerLicenceExpiringSoon().validate(_ctx(session, dev))
    warned = [r for r in results if not r.passed]
    assert len(warned) == 1
    assert warned[0].severity.value == "warning"
    assert warned[0].details["valid_to"] == (today + timedelta(days=10)).isoformat()

    licences[0].valid_to = today + timedelta(days=45)
    await session.flush()
    results = await PropDevBrokerLicenceExpiringSoon().validate(_ctx(session, dev))
    noticed = [r for r in results if not r.passed]
    assert len(noticed) == 1
    assert noticed[0].severity.value == "info"

    licences[0].valid_to = today + timedelta(days=61)
    await session.flush()
    results = await PropDevBrokerLicenceExpiringSoon().validate(_ctx(session, dev))
    assert results and all(r.passed for r in results)


def test_saudi_profile_warns_at_60_and_30_days() -> None:
    assert sorted(broker_licence_policy("SA")["expiry_warning_days"]) == [30, 60]


@pytest.mark.asyncio
async def test_lease_through_a_broker_needs_a_licence_on_the_start_date() -> None:
    from app.modules.leasing.validators import BrokerLicenceRule

    lease = {"id": "L1", "start_date": "2026-03-01", "end_date": "2027-02-28"}
    lic = {"authority_code": "REGA", "status": "active", "valid_from": "2026-01-01", "valid_to": "2026-12-31"}

    async def run(licences, country="SA"):
        data = {"lease": lease, "country": country, "broker": {"id": "b", "name": "B", "licences": licences}}
        return await BrokerLicenceRule().validate(ValidationContext(data=data))

    assert all(r.passed for r in await run([lic]))
    failed = await run([{**lic, "valid_to": "2026-02-01"}])
    assert failed and not failed[0].passed and failed[0].severity.value == "error"
    assert await run([], country="DE") == []
    no_broker = await BrokerLicenceRule().validate(ValidationContext(data={"lease": lease, "country": "SA"}))
    assert no_broker == []


# ── API ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_licence_api_round_trip(client) -> None:
    _uid, _email, headers = await _register_user(client)
    tag = uuid.uuid4().hex[:8]
    broker = await client.post(
        "/api/v1/property-dev/brokers/",
        json={"name": f"Broker {tag}", "license_number": f"BR-{tag}"},
        headers=headers,
    )
    assert broker.status_code == 201, broker.text
    bid = broker.json()["id"]
    body = {
        "authority_code": "rega",
        "licence_number": f"L-{tag}",
        "valid_from": "2026-01-01",
        "valid_to": "2026-12-31",
    }

    created = await client.post(f"/api/v1/property-dev/brokers/{bid}/licences/", json=body, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["authority_code"] == "REGA"
    assert created.json()["status"] == "active"
    lid = created.json()["id"]

    dup = await client.post(f"/api/v1/property-dev/brokers/{bid}/licences/", json=body, headers=headers)
    assert dup.status_code == 409
    backwards = await client.post(
        f"/api/v1/property-dev/brokers/{bid}/licences/",
        json={**body, "licence_number": "X", "valid_to": "2025-01-01"},
        headers=headers,
    )
    assert backwards.status_code == 422

    listed = await client.get(f"/api/v1/property-dev/brokers/{bid}/licences/", headers=headers)
    assert [row["id"] for row in listed.json()] == [lid]
    register = await client.get("/api/v1/property-dev/broker-licences/", headers=headers)
    assert lid in {row["id"] for row in register.json()}

    patched = await client.patch(
        f"/api/v1/property-dev/brokers/{bid}/licences/{lid}", json={"status": "suspended"}, headers=headers
    )
    assert patched.status_code == 200 and patched.json()["status"] == "suspended"
    bad_window = await client.patch(
        f"/api/v1/property-dev/brokers/{bid}/licences/{lid}", json={"valid_to": "2025-06-01"}, headers=headers
    )
    assert bad_window.status_code == 422

    gone = await client.delete(f"/api/v1/property-dev/brokers/{bid}/licences/{lid}", headers=headers)
    assert gone.status_code == 204
    again = await client.delete(f"/api/v1/property-dev/brokers/{bid}/licences/{lid}", headers=headers)
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_demo_leases_go_through_a_licensed_broker(seeded) -> None:
    from app.modules.leasing.models import Lease
    from app.modules.leasing.service import LeasingService

    session, _dev = seeded
    leases = (await session.execute(select(Lease))).scalars().all()
    assert leases and all(lease.ext_refs.get("broker_id") for lease in leases)
    report = await LeasingService(session).validate(leases[0])
    assert not [r for r in report["results"] if r["rule_id"] == "leasing.broker_licence"]
    for lic in (await session.execute(select(BrokerLicence))).scalars():
        lic.status = "revoked"
    await session.flush()
    report = await LeasingService(session).validate(leases[0])
    assert [r for r in report["results"] if r["rule_id"] == "leasing.broker_licence"]
