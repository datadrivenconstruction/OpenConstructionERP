"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠SAFETY PRIMITIVE 1 - cross-tenant data isolation (DB-backed, CI-gated).

These assertions need real rows in PostgreSQL. They run on the transaction-
isolated session from ``tests._pg.transactional_session`` (rolled back on
teardown) and are skipped automatically when no PostgreSQL cluster can be
booted. They prove the scoper never resolves a row outside the caller's project
or workspace, that a foreign project_id yields a refusal (no rows), and that an
admin still cannot reach another workspace.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.saved_views.errors import ScopeDenied
from app.modules.saved_views.scoper import ScopeContext
from app.modules.saved_views.service import SavedViewService

try:
    from tests._pg import transactional_session

    _PG_AVAILABLE = True
except Exception:  # noqa: BLE001
    _PG_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _PG_AVAILABLE, reason="PostgreSQL test cluster unavailable")


def _register_ledger() -> None:
    from app.modules.saved_views.entities import finance_entity
    from app.modules.saved_views.registry import entity_registry

    if entity_registry.get("ledger_entry") is None:
        finance_entity.register()


async def _seed_user(session: AsyncSession, *, role: str = "editor") -> uuid.UUID:
    from app.modules.users.models import User

    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Tester",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed_project(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    pack_slug: str | None = None,
) -> uuid.UUID:
    from app.modules.projects.models import Project

    project = Project(
        name=f"P-{uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        metadata_={"partner_pack": pack_slug} if pack_slug else {},
    )
    session.add(project)
    await session.flush()
    return project.id


async def _seed_ledger(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    ref: str,
    account: str = "330",
) -> None:
    from decimal import Decimal

    from app.modules.finance.models import LedgerEntry

    session.add(
        LedgerEntry(
            project_id=project_id,
            transaction_ref=ref,
            account_code=account,
            debit_amount=Decimal("100"),
            credit_amount=Decimal("0"),
            currency_code="EUR",
            posted_at="2026-01-01",
        )
    )
    await session.flush()


@pytest_asyncio.fixture
async def session():
    _register_ledger()
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_cross_tenant_rows_never_returned(session: AsyncSession):
    """A run pinned to project A in workspace alpha never returns B/beta rows.

    Then mutating the spec to reference B's project_id as a filter VALUE still
    returns only A's rows: the scoper pin wins, a spec value cannot move scope.
    """
    from app.modules.saved_views.schemas import (
        FilterCondition,
        FilterGroup,
        FilterSpec,
    )

    owner = await _seed_user(session)
    project_a = await _seed_project(session, owner, pack_slug="alpha")
    project_b = await _seed_project(session, owner, pack_slug="beta")
    await _seed_ledger(session, project_a, ref="A-1")
    await _seed_ledger(session, project_b, ref="B-1")

    ctx = ScopeContext(
        user_id=owner,
        role="editor",
        project_id=project_a,
        workspace_slug="alpha",
        is_admin=False,
    )
    service = SavedViewService(session)
    result = await service.run_adhoc("ledger_entry", FilterSpec(), ctx)
    refs = {r["transaction_ref"] for r in result.rows}
    assert refs == {"A-1"}

    # Now try to smuggle B's project_id in as a filter value - must not widen.
    smuggle = FilterSpec(
        where=FilterGroup(
            conditions=[
                FilterCondition(field="account_code", op="eq", value="330"),
            ]
        )
    )
    result2 = await service.run_adhoc("ledger_entry", smuggle, ctx)
    refs2 = {r["transaction_ref"] for r in result2.rows}
    assert refs2 == {"A-1"}


@pytest.mark.asyncio
async def test_foreign_project_id_refused(session: AsyncSession):
    """A user who is not a member of project B gets a refusal, no rows."""
    from app.modules.saved_views.schemas import FilterSpec

    owner_b = await _seed_user(session)
    project_b = await _seed_project(session, owner_b, pack_slug="beta")
    await _seed_ledger(session, project_b, ref="B-1")

    stranger = await _seed_user(session)
    ctx = ScopeContext(
        user_id=stranger,
        role="editor",
        project_id=project_b,
        workspace_slug="beta",
        is_admin=False,
    )
    service = SavedViewService(session)
    with pytest.raises(ScopeDenied):
        await service.run_adhoc("ledger_entry", FilterSpec(), ctx)


@pytest.mark.asyncio
async def test_admin_does_not_see_other_workspace(session: AsyncSession):
    """An admin pinned to workspace alpha cannot read project B in beta.

    Admin bypasses the project ACCESS check but NOT the project / workspace pin,
    so pinning to A returns only A even for an admin; and pinning an admin to B
    while their workspace is alpha returns nothing (the workspace pin excludes a
    beta project).
    """
    from app.modules.saved_views.schemas import FilterSpec

    owner = await _seed_user(session)
    project_a = await _seed_project(session, owner, pack_slug="alpha")
    project_b = await _seed_project(session, owner, pack_slug="beta")
    await _seed_ledger(session, project_a, ref="A-1")
    await _seed_ledger(session, project_b, ref="B-1")

    admin = await _seed_user(session, role="admin")
    # Admin pinned to A / alpha sees only A.
    ctx_a = ScopeContext(
        user_id=admin,
        role="admin",
        project_id=project_a,
        workspace_slug="alpha",
        is_admin=True,
    )
    service = SavedViewService(session)
    res_a = await service.run_adhoc("ledger_entry", FilterSpec(), ctx_a)
    assert {r["transaction_ref"] for r in res_a.rows} == {"A-1"}

    # Admin pinned to B but workspace alpha: the workspace pin excludes the beta
    # project, so no rows resolve.
    ctx_b = ScopeContext(
        user_id=admin,
        role="admin",
        project_id=project_b,
        workspace_slug="alpha",
        is_admin=True,
    )
    res_b = await service.run_adhoc("ledger_entry", FilterSpec(), ctx_b)
    assert res_b.rows == []
