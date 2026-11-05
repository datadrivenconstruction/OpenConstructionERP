# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Fixtures for the data feed tests: a rolled-back PostgreSQL session and an app with only this router."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_optional_user_payload, get_session
from app.modules.bi_feed.router import router as bi_feed_router
from app.modules.bi_feed.validators import register_bi_feed_rules
from app.modules.boq.models import BOQ, Position
from app.modules.boq.permissions import register_boq_permissions
from app.modules.finance.models import Invoice
from app.modules.finance.permissions import register_finance_permissions
from app.modules.procurement.permissions import register_procurement_permissions
from app.modules.projects.models import Project
from app.modules.projects.permissions import register_project_permissions
from app.modules.schedule.permissions import register_schedule_permissions
from app.modules.users.models import APIKey, User
from tests._pg import transactional_session

PREFIX = "/v1/bi-feed"


@pytest.fixture(scope="session", autouse=True)
def _rules_registered() -> None:
    register_bi_feed_rules()
    # A feed is gated by the read permission of its source module; the app registers these at start-up.
    for register in (
        register_project_permissions,
        register_boq_permissions,
        register_finance_permissions,
        register_procurement_permissions,
        register_schedule_permissions,
    ):
        register()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def make_user(session: AsyncSession, *, role: str = "editor") -> User:
    user = User(email=f"bi-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", role=role, is_active=True)
    session.add(user)
    await session.flush()
    return user


async def make_project(session: AsyncSession, owner_id: uuid.UUID, *, currency: str = "EUR") -> Project:
    project = Project(name=f"BI {uuid.uuid4().hex[:6]}", owner_id=owner_id, currency=currency)
    session.add(project)
    await session.flush()
    return project


async def make_boq(session: AsyncSession, project_id: uuid.UUID) -> BOQ:
    boq = BOQ(project_id=project_id, name="Main BOQ")
    session.add(boq)
    await session.flush()
    return boq


async def make_position(
    session: AsyncSession,
    boq_id: uuid.UUID,
    *,
    ordinal: str = "01",
    position_id: uuid.UUID | None = None,
    **fields: Any,
) -> Position:
    values: dict[str, Any] = {
        "boq_id": boq_id,
        "ordinal": ordinal,
        "description": "Concrete C30/37",
        "unit": "m3",
        "quantity": "10",
        "unit_rate": "100.50",
        "total": "1005.00",
        "created_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    }
    values.update(fields)
    if position_id is not None:
        values["id"] = position_id
    position = Position(**values)
    session.add(position)
    await session.flush()
    return position


async def make_invoice(session: AsyncSession, project_id: uuid.UUID, **fields: Any) -> Invoice:
    values: dict[str, Any] = {
        "project_id": project_id,
        "invoice_direction": "payable",
        "invoice_number": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": "2026-01-15",
        "currency_code": "EUR",
    }
    values.update(fields)
    invoice = Invoice(**values)
    session.add(invoice)
    await session.flush()
    return invoice


async def make_key(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    permissions: list[str] | None = None,
    active: bool = True,
    expires_in: timedelta | None = None,
) -> str:
    """Persist an API key and return the secret a client would send."""
    secret = f"oe_{uuid.uuid4().hex}"
    session.add(
        APIKey(
            user_id=user_id,
            name="BI",
            key_hash=hashlib.sha256(secret.encode()).hexdigest(),
            key_prefix=secret[:8],
            is_active=active,
            expires_at=None if expires_in is None else datetime.now(UTC) + expires_in,
            permissions=["bi:read"] if permissions is None else permissions,
        )
    )
    await session.flush()
    return secret


def build_app(db_session: AsyncSession) -> FastAPI:
    """The router on the test session. ``X-Test-User`` stands in for a bearer token."""
    app = FastAPI()
    app.include_router(bi_feed_router, prefix=PREFIX)

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _payload(request: Request) -> dict[str, Any] | None:
        who = request.headers.get("x-test-user")
        return {"sub": who, "role": "editor", "permissions": []} if who else None

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_optional_user_payload] = _payload
    return app


def http_client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
