# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The off-plan Riyadh demo on real PostgreSQL: every screen has rows, the escrow cap holds, Ejar file exports."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.core.demo_real_estate import seed_real_estate_demo
from app.core.validation.engine import ValidationContext
from app.core.validation.rules import PropDevEscrowReleaseWithinProgress
from app.modules.leasing.service import LeasingService
from app.modules.leasing.validators import register_leasing_validation_rules
from app.modules.projects.models import Project
from app.modules.property_dev.models import Development, EscrowAccount, EscrowTransaction
from app.modules.service_charges.models import ChargeDemand
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_leasing_validation_rules()
    async with transactional_session() as s:
        yield s


async def _project(session) -> tuple[uuid.UUID, uuid.UUID]:
    u = User(email=f"re-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
    session.add(u)
    await session.flush()
    p = Project(name="Riyadh off-plan", owner_id=u.id, currency="SAR", country_code="SA")
    session.add(p)
    await session.flush()
    return p.id, u.id


async def test_demo_fills_sales_leasing_and_service_charges(db_session) -> None:
    project_id, owner = await _project(db_session)
    out = await seed_real_estate_demo(db_session, project_id, owner, "residential-riyadh-offplan")
    assert out["property_dev_units"] == 56
    assert out["property_dev_contracts"] > 20
    assert out["leases"] == 2
    assert out["service_charge_units"] == 56
    assert out["service_charge_demands"] == 56 * 3
    demands = (await db_session.execute(select(func.count()).select_from(ChargeDemand))).scalar()
    assert demands >= 56 * 3

    dev = (await db_session.execute(select(Development).where(Development.project_id == project_id))).scalar_one()
    assert dev.metadata_["regulator"] == "REGA"
    ctx = ValidationContext(data={}, project_id=str(dev.id), metadata={"session": db_session, "development_id": dev.id})
    results = await PropDevEscrowReleaseWithinProgress().validate(ctx)
    assert results and all(r.passed for r in results)

    # An over-release is caught.
    acc = (await db_session.execute(select(EscrowAccount).where(EscrowAccount.development_id == dev.id))).scalar_one()
    db_session.add(
        EscrowTransaction(
            escrow_account_id=acc.id,
            direction="debit",
            amount=10**9,
            currency="SAR",
            source_type="release",
            transaction_date="2026-10-01",
        )
    )
    await db_session.flush()
    results = await PropDevEscrowReleaseWithinProgress().validate(ctx)
    assert any(not r.passed for r in results)

    svc = LeasingService(db_session)
    leases = await svc.repo.list_leases([project_id], limit=10)
    assert {x.status for x in leases} == {"active"}
    body, media, _ = await svc.export(leases, "ejar")
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
    assert media == "text/csv" and len(rows) == 2
    assert all(r["tenant_id_type"] == "national_id" and len(r["tenant_id_number"]) == 10 for r in rows)
    assert all(r["start_date_hijri"].startswith("1447-") for r in rows)
