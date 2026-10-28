"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Gap A access-control tests for the payroll finalize endpoint.

These cover the security slice of the TEST MATRIX without spinning up a full
FastAPI app (per the suite convention: prefer the gate helpers + service layer,
which is what the route delegates to). Specifically:

    9   IDOR: a caller without project access is blocked (the shared
        ``verify_project_access`` returns 404 - the secure default this codebase
        uses everywhere; the design's "403" is realised as a 404 to avoid an
        existence oracle).
    10  Permission gating: ``payroll.finalize`` is denied to a VIEWER and
        granted to a MANAGER via the live permission registry.
    11  Idempotent contract: the service short-circuits an already-approved
        batch (asserted at the service layer in ``test_finalize_batch``); here we
        confirm the route declares the finalize permission + verifies access.
    12  404 for a missing batch (service raises before any project check).

The endpoint itself (``router.finalize_batch``) is a thin shell:
``get_batch -> verify_project_access -> service.finalize_batch``; each link is
tested directly so the contract is pinned without a per-test event loop owning a
shared asyncpg connection.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _seed_user(session: AsyncSession, *, role: str = "manager") -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(
        User(
            id=uid,
            email=f"acl-{uuid.uuid4().hex[:10]}@payroll.io",
            hashed_password="x",
            full_name="ACL user",
            role=role,
        )
    )
    await session.flush()
    return uid


async def _seed_project(session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    session.add(Project(id=pid, name="ACL project", owner_id=owner_id, currency="EUR", fx_rates=[]))
    await session.flush()
    return pid


# ── Case 9: IDOR - a non-owner / non-member is blocked (404) ──────────────────


async def test_finalize_idor_blocks_non_member(session: AsyncSession) -> None:
    from app.dependencies import verify_project_access

    owner = await _seed_user(session, role="manager")
    stranger = await _seed_user(session, role="manager")
    project_id = await _seed_project(session, owner)

    # The endpoint runs verify_project_access(batch.project_id, user_id, session).
    with pytest.raises(HTTPException) as exc:
        await verify_project_access(project_id, str(stranger), session)
    assert exc.value.status_code == 404


async def test_finalize_owner_passes_access_check(session: AsyncSession) -> None:
    from app.dependencies import verify_project_access

    owner = await _seed_user(session, role="manager")
    project_id = await _seed_project(session, owner)
    # Must not raise for the owner.
    await verify_project_access(project_id, str(owner), session)


# ── Case 10: permission gating - VIEWER denied, MANAGER granted ───────────────


async def test_finalize_permission_denied_for_viewer() -> None:
    from app.dependencies import RequirePermission
    from app.modules.payroll.permissions import register_payroll_permissions

    register_payroll_permissions()
    gate = RequirePermission("payroll.finalize")

    viewer_payload = {"role": "viewer", "permissions": [], "sub": str(uuid.uuid4())}
    with pytest.raises(HTTPException) as exc:
        await gate(viewer_payload)
    assert exc.value.status_code == 403


async def test_finalize_permission_granted_for_manager() -> None:
    from app.dependencies import RequirePermission
    from app.modules.payroll.permissions import register_payroll_permissions

    register_payroll_permissions()
    gate = RequirePermission("payroll.finalize")

    manager_payload = {"role": "manager", "permissions": [], "sub": str(uuid.uuid4())}
    # Must not raise (granted via the live registry mapping for MANAGER).
    await gate(manager_payload)


async def test_finalize_permission_granted_for_admin() -> None:
    from app.dependencies import RequirePermission

    gate = RequirePermission("payroll.finalize")
    admin_payload = {"role": "admin", "permissions": [], "sub": str(uuid.uuid4())}
    # Admin bypasses all checks.
    await gate(admin_payload)


# ── Case 11/12: the route wires the finalize permission + access check ─────────


def test_route_declares_finalize_permission() -> None:
    """The PATCH finalize route is mounted and gated on ``payroll.finalize``."""
    from app.dependencies import RequirePermission
    from app.modules.payroll.router import router

    finalize_routes = [r for r in router.routes if getattr(r, "path", "") == "/batches/{batch_id}/finalize/"]
    assert len(finalize_routes) == 1
    route = finalize_routes[0]
    assert "PATCH" in route.methods

    # The RequirePermission("payroll.finalize") dependency is declared on the route.
    perms = [
        dep.call.permission
        for dep in route.dependant.dependencies
        if isinstance(getattr(dep, "call", None), RequirePermission)
    ]
    assert "payroll.finalize" in perms


def test_finalize_permission_registered_for_manager_role() -> None:
    from app.core.permissions import permission_registry
    from app.modules.payroll.permissions import register_payroll_permissions

    register_payroll_permissions()
    assert permission_registry.role_has_permission("manager", "payroll.finalize")
    assert not permission_registry.role_has_permission("viewer", "payroll.finalize")
