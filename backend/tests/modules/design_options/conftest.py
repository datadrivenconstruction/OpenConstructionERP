"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the Design Options test suite.

The session fixture runs against the shared PostgreSQL unit database from
``tests/_pg.py``, inside an outer transaction that is rolled back on teardown.

Foreign keys stay ON deliberately (no ``disable_fks``): the module's access
guard resolves real ``User`` and ``Project`` rows, and the delete-cascade
behaviour under test is a database-level ``ON DELETE CASCADE`` chain
(project -> set -> option) that never fires with the replication role set.

The module's six validation rules are registered here. The application registers
them from its ``on_startup`` hook, which no test process runs, so without this
the ``design_options`` rule set resolves to zero rules and the engine reports it
as unsupported - which is indistinguishable from "the rules ran and found
nothing". ``tests/test_design_options_rule_registry.py`` guards that assumption
explicitly.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
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
from app.modules.boq.models import BOQ, Position
from app.modules.design_options.models import DesignOption, DesignOptionSet
from app.modules.design_options.router import router as design_options_router
from app.modules.design_options.validators import register_design_options_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

API_PREFIX = "/v1/design-options"


@pytest.fixture(scope="session", autouse=True)
def _design_options_rules_registered() -> None:
    """Register the module's rule set for the whole test session."""
    register_design_options_rules()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session() as s:
        yield s


# ── Row factories ────────────────────────────────────────────────────────────


async def make_user(session: AsyncSession, *, role: str = "editor") -> User:
    """Persist a user with an explicit role (non-admin by default).

    The access guard reads ``User.role`` from the database, not from the JWT
    payload, so an IDOR test needs a persisted non-admin row to be meaningful.
    """
    user = User(
        email=f"do-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def make_project(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    currency: str = "EUR",
    gross_floor_area: str | None = "1000",
    classification_standard: str = "din276",
    fx_rates: list[dict[str, str]] | None = None,
) -> Project:
    """Persist a project owned by ``owner_id``."""
    project = Project(
        name=f"Design options {uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        currency=currency,
        gross_floor_area=gross_floor_area,
        classification_standard=classification_standard,
        fx_rates=fx_rates or [],
    )
    session.add(project)
    await session.flush()
    return project


async def make_set(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    name: str = "Frame options",
    comparison_currency: str = "",
    baseline_option_id: uuid.UUID | None = None,
) -> DesignOptionSet:
    """Persist a design-option set."""
    option_set = DesignOptionSet(
        project_id=project_id,
        name=name,
        comparison_currency=comparison_currency,
        baseline_option_id=baseline_option_id,
    )
    session.add(option_set)
    await session.flush()
    return option_set


async def make_option(
    session: AsyncSession,
    option_set: DesignOptionSet,
    *,
    name: str = "Option",
    sort_order: int = 0,
    **fields: Any,
) -> DesignOption:
    """Persist an option inside ``option_set``."""
    option = DesignOption(
        set_id=option_set.id,
        project_id=option_set.project_id,
        name=name,
        sort_order=sort_order,
        **fields,
    )
    session.add(option)
    await session.flush()
    return option


async def make_boq(session: AsyncSession, project_id: uuid.UUID, *, name: str = "Option BOQ") -> BOQ:
    """Persist a bill of quantities for a project."""
    boq = BOQ(project_id=project_id, name=name, estimate_type="design_option")
    session.add(boq)
    await session.flush()
    return boq


async def make_position(
    session: AsyncSession,
    boq_id: uuid.UUID,
    *,
    ordinal: str = "01.001",
    description: str = "Concrete wall",
    unit: str = "m3",
    quantity: str = "10",
    unit_rate: str = "100",
    total: str | None = None,
    classification: dict[str, str] | None = None,
    metadata_: dict[str, Any] | None = None,
) -> Position:
    """Persist a leaf position with money as decimal strings."""
    position = Position(
        boq_id=boq_id,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total=total if total is not None else str(float(quantity) * float(unit_rate)),
        classification={"din276": "330"} if classification is None else classification,
        metadata_=metadata_ or {},
    )
    session.add(position)
    await session.flush()
    return position


# ── HTTP plumbing ────────────────────────────────────────────────────────────


def build_app(db_session: AsyncSession, *, caller_id: uuid.UUID | str) -> FastAPI:
    """Mount the module router with the test session and a fixed caller."""
    app = FastAPI()
    app.include_router(design_options_router, prefix=API_PREFIX)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _user_override() -> str:
        return str(caller_id)

    async def _payload_override() -> dict[str, Any]:
        return {"sub": str(caller_id), "role": "editor", "permissions": []}

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
