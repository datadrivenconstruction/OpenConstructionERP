# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the Currency / FX test suite.

The session fixture runs against the shared PostgreSQL unit database from
``tests/_pg.py``, inside an outer transaction that is rolled back on teardown.

Two things this file deliberately guarantees:

* **The module's validation rules are registered.** The application registers
  them from its ``on_startup`` hook, which no test process runs, so without this
  the ``fx`` rule set resolves to zero rules and the engine reports it as
  unsupported - which is indistinguishable from "the rules ran and found
  nothing".
* **No test touches the network.** Every fixture that exercises a fetch stubs
  the transport method (``_fetch_ecb_xml`` / ``_fetch_ppp``), never the parse or
  the store, so the parsing, upsert and provenance columns are all genuinely
  exercised while the socket never opens.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.fx import repository as repo
from app.modules.fx.models import FxPolicy, FxRateSet
from app.modules.fx.permissions import register_fx_permissions
from app.modules.fx.router import router as fx_router
from app.modules.fx.validators import register_fx_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

API_PREFIX = "/v1/fx"

#: A real ECB ``eurofxref-daily`` document, trimmed to three currencies. Kept
#: namespaced exactly like the live feed so the namespace-agnostic parser is
#: tested against the shape it actually meets.
ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <gesmes:Sender>
    <gesmes:name>European Central Bank</gesmes:name>
  </gesmes:Sender>
  <Cube>
    <Cube time="2026-03-02">
      <Cube currency="USD" rate="1.0850"/>
      <Cube currency="TRY" rate="42.5000"/>
      <Cube currency="CNY" rate="7.8000"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


@pytest.fixture(scope="session", autouse=True)
def _fx_module_registered() -> None:
    """Register the module's rule set and permissions for the whole test session.

    Both are process-global registries that the application populates from
    ``on_startup``. Doing it once here rather than inside individual tests keeps
    the mutation out of test bodies, where it would leak into whatever runs next
    depending on ordering.
    """
    register_fx_rules()
    register_fx_permissions()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session() as s:
        yield s


# ── Row factories ────────────────────────────────────────────────────────────


async def make_rate_set(
    session: AsyncSession,
    *,
    rate_date: date,
    rates: Mapping[str, str],
    base_currency: str = "EUR",
    source: str = "ecb",
    source_ref: str = "https://example.invalid/feed.xml",
    note: str = "",
    lock: bool = False,
) -> FxRateSet:
    """Persist a rate set with its quotes, rates given as decimal strings."""
    return await repo.upsert_rate_set(
        session,
        base_currency=base_currency,
        rate_date=rate_date,
        source=source,
        rates={code: Decimal(value) for code, value in rates.items()},
        source_ref=source_ref,
        note=note,
        lock=lock,
    )


async def make_policy(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    estimating_currency: str = "EUR",
    procurement_currency: str = "TRY",
    reporting_currency: str = "USD",
    rate_mode: str = "live",
    pinned_rate_set_id: uuid.UUID | None = None,
    max_rate_age_days: int = 30,
) -> FxPolicy:
    """Persist a project FX policy, on a real project unless one is named.

    The policy routes check access to the project, so a policy hung off an id
    with no project behind it would read as 404 to every caller.
    """
    if project_id is None:
        project_id = (await make_project(session)).id
    return await repo.upsert_policy(
        session,
        project_id,
        estimating_currency=estimating_currency,
        procurement_currency=procurement_currency,
        reporting_currency=reporting_currency,
        rate_mode=rate_mode,
        pinned_rate_set_id=pinned_rate_set_id,
        max_rate_age_days=max_rate_age_days,
    )


async def make_user(session: AsyncSession, *, role: str = "admin", user_id: uuid.UUID | None = None) -> User:
    """Persist a user; the project access check reads the role from this row."""
    user = User(
        id=user_id or uuid.uuid4(),
        email=f"fx-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def make_project(session: AsyncSession, owner: User | None = None) -> Project:
    """Persist a project, owned by a fresh user unless an owner is given."""
    owner = owner or await make_user(session, role="manager")
    project = Project(name=f"FX {uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


# ── HTTP plumbing ────────────────────────────────────────────────────────────


def build_app(db_session: AsyncSession, *, caller_id: uuid.UUID | str, role: str = "admin") -> FastAPI:
    """Mount the FX router with the test session and a fixed caller.

    The default caller is an admin so permission wiring never masks a genuine
    routing or serialisation failure; the permission gates themselves are
    exercised by passing a narrower role.
    """
    app = FastAPI()
    app.include_router(fx_router, prefix=API_PREFIX)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _user_override() -> str:
        return str(caller_id)

    async def _payload_override() -> dict[str, Any]:
        return {"sub": str(caller_id), "role": role, "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


def http_client(app: FastAPI) -> AsyncClient:
    """In-process async client bound to ``app`` on the current event loop.

    ``httpx.AsyncClient`` over ``ASGITransport`` keeps the app on the test's own
    event loop; the synchronous ``TestClient`` would drive it from a worker
    thread on a second loop and break the asyncpg session created here.
    """
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
