# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""``GET /finance/inbox`` reaches the inbox list, not the get-invoice route.

The inbox sub-router is included at the bottom of ``finance/router.py``, after
``GET /{invoice_id}``. With a bare parameter that route matched ``/inbox`` first
and answered 422 ("inbox" is not a UUID), so the Invoice Inbox tab showed an
error on every install. The router is mounted the way the module loader mounts
it, through ``include_router`` with a prefix, so the order is the real one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.finance.router import router as finance_router
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _owner_and_project(session) -> tuple[str, uuid.UUID]:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(name="Inbox project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return str(user.id), project.id


def _app(db_session, caller_id: str) -> FastAPI:
    app = FastAPI()
    app.include_router(finance_router, prefix="/api/v1/finance")

    async def _session():
        yield db_session

    async def _user() -> str:
        return caller_id

    async def _payload() -> dict:
        # Admin payload: RequirePermission is not what this file tests.
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


async def _get(app: FastAPI, url: str, **params) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(url, params=params)


async def test_the_inbox_list_answers_with_the_list(db_session) -> None:
    caller, project_id = await _owner_and_project(db_session)
    # The exact call InvoiceInboxTab makes: no trailing slash, project_id in the query.
    resp = await _get(_app(db_session, caller), "/api/v1/finance/inbox", project_id=str(project_id))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": [], "total": 0}


async def test_an_invoice_id_still_reaches_get_invoice(db_session) -> None:
    caller, _project_id = await _owner_and_project(db_session)
    resp = await _get(_app(db_session, caller), f"/api/v1/finance/{uuid.uuid4()}")
    # get_invoice ran and found nothing: a 404 from the handler, not a 422 from routing.
    assert resp.status_code == 404, resp.text


async def test_a_word_under_finance_is_not_taken_for_an_invoice_id(db_session) -> None:
    caller, _project_id = await _owner_and_project(db_session)
    resp = await _get(_app(db_session, caller), "/api/v1/finance/not-an-invoice")
    assert resp.status_code == 404, resp.text
