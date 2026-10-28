"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Wave 8 (Tests) - RFI cross-tenant IDOR 404 through the REAL access guard.

Every prior RFI endpoint test either overrides ``verify_project_access`` with
a stub (``test_rfi_attachments`` / ``test_rfi_variation_idempotency`` /
``test_rfi_overdue_and_distribution``) - which is in fact a no-op, since the
router calls ``verify_project_access`` as a DIRECT function, not via
``Depends`` - or only asserts the guard is *called*
(``test_rfi_state_fsm.TestCloseEndpointIDOR`` stubs it). None of them prove
that the genuine ``app.dependencies.verify_project_access`` actually answers a
real non-owner / non-admin / non-member caller with a 404 across the RFI
lifecycle. That is the single IDOR case the module most needs pinned, because a
regression there silently turns every RFI endpoint into a cross-tenant oracle.

These tests invoke the route handler coroutines DIRECTLY (no ``TestClient``),
passing a real ``RFIService`` bound to a real PostgreSQL session and the REAL
``verify_project_access``. Calling the handler directly:

* runs on the test's own event loop (so it is locally runnable, unlike the
  ``TestClient``-threaded suites that hit the asyncpg cross-loop issue on
  Windows), and
* bypasses the decorator ``dependencies=[RequirePermission(...)]`` (a route
  decoration, not a handler parameter) so we isolate the IDOR access guard
  rather than the coarse RBAC gate.

The caller is neither the project owner, nor an admin, nor a team member, so
the real guard must raise ``HTTPException(404)`` (never 403, never a 200) -
the IDOR-safe "resource missing == access denied" policy. A control class
proves the very same handlers succeed for the legitimate owner, so the 404s
are the guard firing and not a broken fixture.

DB-backed; runs in CI against the shared ``oe_test_unit`` PostgreSQL database
inside a transaction rolled back on teardown (``tests._pg``).
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.projects.models import Project
from app.modules.rfi import router as rfi_router
from app.modules.rfi.schemas import RFICreate, RFIRespondRequest, RFIUpdate
from app.modules.rfi.service import RFIService
from app.modules.users.models import User
from tests._pg import transactional_session

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _make_user(session) -> uuid.UUID:
    # NOT admin - admins get an unconditional bypass inside
    # verify_project_access, which would mask the IDOR check we are pinning.
    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="manager")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="Tenant project", owner_id=owner_id, currency="EUR")
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


async def _seed_answered_cost_rfi(session, owner: str, project_id: uuid.UUID):
    """An ``answered`` RFI with a cost impact, ready for any lifecycle call."""
    service = RFIService(session)
    rfi = await service.create_rfi(
        RFICreate(
            project_id=project_id,
            subject="Cross-tenant target",
            question="Which spec applies?",
            status="open",
            cost_impact=True,
            cost_impact_value="5000.00",
        ),
        user_id=owner,
    )
    await service.respond_to_rfi(
        rfi.id,
        "The 2026 spec applies.",
        responded_by=owner,
        actor_role="admin",
    )
    await session.flush()
    return rfi


class TestCrossTenantIDOR:
    """A manager with NO relation to the project must get 404 on every RFI
    handler that resolves an existing row - the canonical IDOR case, asserted
    through the real ``verify_project_access``.
    """

    @pytest.mark.asyncio
    async def test_get_rfi_cross_tenant_is_404(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)
        attacker = str(await _make_user(db_session))

        with pytest.raises(HTTPException) as exc:
            await rfi_router.get_rfi(
                rfi_id=rfi.id,
                session=db_session,
                user_id=attacker,
                service=RFIService(db_session),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_rfi_cross_tenant_is_404(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)
        attacker = str(await _make_user(db_session))

        with pytest.raises(HTTPException) as exc:
            await rfi_router.update_rfi(
                rfi_id=rfi.id,
                data=RFIUpdate(subject="hijacked"),
                session=db_session,
                payload={"sub": attacker, "role": "manager"},
                user_id=attacker,
                service=RFIService(db_session),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_respond_cross_tenant_is_404(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        # Open (not answered) so a successful respond would be a 200 - proving
        # the 404 is the access guard, not the FSM source-state check.
        service = RFIService(db_session)
        rfi = await service.create_rfi(
            RFICreate(project_id=project_id, subject="Respond target", question="?", status="open"),
            user_id=owner,
        )
        await db_session.flush()
        attacker = str(await _make_user(db_session))

        with pytest.raises(HTTPException) as exc:
            await rfi_router.respond_to_rfi(
                rfi_id=rfi.id,
                body=RFIRespondRequest(official_response="Injected answer"),
                user_id=attacker,
                session=db_session,
                payload={"sub": attacker, "role": "manager"},
                service=RFIService(db_session),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_close_cross_tenant_is_404(self, db_session) -> None:
        # BUG-RFI-IDOR-CLOSE regression guard, end-to-end through the real
        # guard rather than a stubbed verify.
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)
        attacker = str(await _make_user(db_session))

        with pytest.raises(HTTPException) as exc:
            await rfi_router.close_rfi(
                rfi_id=rfi.id,
                user_id=attacker,
                session=db_session,
                service=RFIService(db_session),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_cross_tenant_is_404(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)
        attacker = str(await _make_user(db_session))

        with pytest.raises(HTTPException) as exc:
            await rfi_router.delete_rfi(
                rfi_id=rfi.id,
                session=db_session,
                user_id=attacker,
                service=RFIService(db_session),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_variation_cross_tenant_is_404(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)
        attacker = str(await _make_user(db_session))

        with pytest.raises(HTTPException) as exc:
            await rfi_router.create_variation_from_rfi(
                rfi_id=rfi.id,
                user_id=attacker,
                session=db_session,
                service=RFIService(db_session),
            )
        # The IDOR guard runs before the cost-impact / status checks, so a
        # cross-tenant caller can never learn whether the RFI is variation
        # eligible.
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_download_attachment_cross_tenant_is_404(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)
        attacker = str(await _make_user(db_session))

        # Index 0 - even an out-of-range index is masked by the access guard
        # (404 from verify, before the attachment-bounds 404), so the caller
        # learns nothing about the row's attachment count.
        with pytest.raises(HTTPException) as exc:
            await rfi_router.download_rfi_attachment(
                rfi_id=rfi.id,
                index=0,
                session=db_session,
                user_id=attacker,
                service=RFIService(db_session),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_stats_cross_tenant_is_404(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        await _seed_answered_cost_rfi(db_session, owner, project_id)
        attacker = str(await _make_user(db_session))

        with pytest.raises(HTTPException) as exc:
            await rfi_router.rfi_stats(
                user_id=attacker,
                session=db_session,
                project_id=project_id,
                service=RFIService(db_session),
            )
        assert exc.value.status_code == 404


class TestLegitimateOwnerControl:
    """Same handlers, but the caller IS the owner: each must succeed. This
    proves the 404s above come from the access guard, not a broken fixture.
    """

    @pytest.mark.asyncio
    async def test_owner_gets_rfi_200(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)

        out = await rfi_router.get_rfi(
            rfi_id=rfi.id,
            session=db_session,
            user_id=owner,
            service=RFIService(db_session),
        )
        assert str(out.id) == str(rfi.id)

    @pytest.mark.asyncio
    async def test_owner_closes_rfi_200(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)

        out = await rfi_router.close_rfi(
            rfi_id=rfi.id,
            user_id=owner,
            session=db_session,
            service=RFIService(db_session),
        )
        assert out.status == "closed"

    @pytest.mark.asyncio
    async def test_owner_stats_200(self, db_session) -> None:
        owner = str(await _make_user(db_session))
        project_id = await _make_project(db_session, uuid.UUID(owner))
        await _seed_answered_cost_rfi(db_session, owner, project_id)

        stats = await rfi_router.rfi_stats(
            user_id=owner,
            session=db_session,
            project_id=project_id,
            service=RFIService(db_session),
        )
        assert stats.total == 1
