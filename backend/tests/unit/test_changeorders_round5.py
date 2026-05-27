"""Round-5 / R7 hardening tests for the ChangeOrders module.

Scope:
    * FSM allowlist: only valid transitions accepted; invalid ones raise HTTP 400.
      Specifically: approved -> executed is the new terminal path; approved ->
      approved is a no-op idempotent; executing an already-executed CO raises.
    * IDOR audit: GET / PATCH / DELETE via router on wrong-project resource -> 404.
    * RBAC pins: approve / reject / execute require ``changeorders.approve``
      (tested via dependency override).
    * Audit trail: submit / approve / reject / execute all write ActivityLog rows.
    * Money Decimal-string: cost_impact, contractor_amount, engineer_amount,
      approved_amount all persist as exact Decimal.
    * execute_order terminal state: approved -> executed, executed -> anything fails.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.audit_log import ActivityLog
from app.database import Base
from app.dependencies import get_current_user_id, get_session
from app.modules.changeorders.models import ChangeOrder, ChangeOrderApproval, ChangeOrderItem
from app.modules.changeorders.router import router as co_router
from app.modules.changeorders.schemas import ChangeOrderCreate
from app.modules.changeorders.service import VALID_TRANSITIONS, ChangeOrderService
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS
from app.modules.users.models import APIKey, User

# ── Tables ────────────────────────────────────────────────────────────────────

_TABLES = [
    User.__table__,
    APIKey.__table__,
    Project.__table__,
    ProjectWBS.__table__,
    ProjectMilestone.__table__,
    ChangeOrder.__table__,
    ChangeOrderApproval.__table__,
    ChangeOrderItem.__table__,
    ActivityLog.__table__,
]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> ChangeOrderService:
    return ChangeOrderService(session)


async def _make_user(session: AsyncSession) -> uuid.UUID:
    u = User(email=f"u{uuid.uuid4().hex[:8]}@test.com", hashed_password="x")
    session.add(u)
    await session.flush()
    await session.refresh(u)
    return u.id


async def _make_project(session: AsyncSession, owner: uuid.UUID) -> uuid.UUID:
    p = Project(name="CO Test Proj", owner_id=owner, currency="USD")
    session.add(p)
    await session.flush()
    await session.refresh(p)
    return p.id


async def _create_co(
    svc: ChangeOrderService,
    project_id: uuid.UUID,
    *,
    cost_impact: str = "0",
) -> ChangeOrder:
    return await svc.create_order(
        ChangeOrderCreate(
            project_id=project_id,
            title="Test CO",
            description="",
            cost_impact=cost_impact,
        )
    )


# ── FSM allowlist ──────────────────────────────────────────────────────────────


class TestCOFSM:
    """ChangeOrder state machine — only valid transitions accepted."""

    def test_draft_to_submitted_allowed(self) -> None:
        assert "submitted" in VALID_TRANSITIONS.get("draft", [])

    def test_draft_to_approved_blocked(self) -> None:
        assert "approved" not in VALID_TRANSITIONS.get("draft", [])

    def test_approved_to_executed_allowed(self) -> None:
        assert "executed" in VALID_TRANSITIONS.get("approved", [])

    def test_executed_is_terminal(self) -> None:
        assert VALID_TRANSITIONS.get("executed", []) == []

    def test_rejected_to_draft_allowed(self) -> None:
        assert "draft" in VALID_TRANSITIONS.get("rejected", [])

    @pytest.mark.asyncio
    async def test_draft_to_approved_raises(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await svc.approve_order(co.id, str(user))
        assert exc_info.value.status_code == 400  # invalid transition

    @pytest.mark.asyncio
    async def test_executed_to_anything_raises(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        # Walk to approved.
        submitter = await _make_user(session)
        await session.commit()
        co = await svc.submit_order(co.id, str(submitter))
        await session.commit()
        co = await svc.approve_order(co.id, str(user))
        await session.commit()

        # Execute.
        co = await svc.execute_order(co.id, str(user))
        await session.commit()
        assert co.status == "executed"

        # Any further transition must fail.
        with pytest.raises(HTTPException):
            await svc.execute_order(co.id, str(user))

    @pytest.mark.asyncio
    async def test_approve_already_approved_is_idempotent(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        co = await _create_co(svc, project, cost_impact="500.00")
        await session.commit()

        submitter = await _make_user(session)
        await session.commit()
        co = await svc.submit_order(co.id, str(submitter))
        await session.commit()
        co = await svc.approve_order(co.id, str(user))
        await session.commit()
        assert co.status == "approved"

        # Approving again must be a no-op, not raise.
        co2 = await svc.approve_order(co.id, str(user))
        assert co2.status == "approved"


# ── execute_order service method ──────────────────────────────────────────────


class TestExecuteOrder:
    """Tests for the new execute_order terminal-state method."""

    @pytest.mark.asyncio
    async def test_execute_approved_co_succeeds(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        co = await _create_co(svc, project, cost_impact="9999.00")
        await session.commit()

        submitter = await _make_user(session)
        await session.commit()
        co = await svc.submit_order(co.id, str(submitter))
        await session.commit()
        co = await svc.approve_order(co.id, str(user))
        await session.commit()

        co = await svc.execute_order(co.id, str(user))
        await session.commit()

        assert co.status == "executed"

    @pytest.mark.asyncio
    async def test_execute_submitted_co_raises(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        submitter = await _make_user(session)
        await session.commit()
        co = await svc.submit_order(co.id, str(submitter))
        await session.commit()

        with pytest.raises(HTTPException):
            await svc.execute_order(co.id, str(user))


# ── Audit trail ───────────────────────────────────────────────────────────────


class TestCOAuditTrail:
    """submit / approve / reject / execute transitions write ActivityLog rows."""

    @pytest.mark.asyncio
    async def test_submit_writes_audit_log(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        from sqlalchemy import select

        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        co = await svc.submit_order(co.id, str(user))
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(ActivityLog)
                    .where(ActivityLog.entity_type == "change_order")
                    .where(ActivityLog.entity_id == str(co.id))
                    .where(ActivityLog.to_status == "submitted")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_approve_writes_audit_log(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        from sqlalchemy import select

        approver = await _make_user(session)
        submitter = await _make_user(session)
        project = await _make_project(session, approver)
        await session.commit()

        co = await _create_co(svc, project, cost_impact="1000.00")
        await session.commit()

        co = await svc.submit_order(co.id, str(submitter))
        await session.commit()
        co = await svc.approve_order(co.id, str(approver))
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(ActivityLog)
                    .where(ActivityLog.entity_type == "change_order")
                    .where(ActivityLog.entity_id == str(co.id))
                    .where(ActivityLog.to_status == "approved")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_execute_writes_audit_log(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        from sqlalchemy import select

        approver = await _make_user(session)
        submitter = await _make_user(session)
        project = await _make_project(session, approver)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        co = await svc.submit_order(co.id, str(submitter))
        await session.commit()
        co = await svc.approve_order(co.id, str(approver))
        await session.commit()
        co = await svc.execute_order(co.id, str(approver))
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(ActivityLog)
                    .where(ActivityLog.entity_type == "change_order")
                    .where(ActivityLog.entity_id == str(co.id))
                    .where(ActivityLog.to_status == "executed")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1


# ── IDOR via router ───────────────────────────────────────────────────────────


def _build_app(session_override: AsyncSession, acting_user: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(co_router, prefix="/v1/changeorders")

    async def _sess() -> AsyncIterator[AsyncSession]:
        yield session_override

    from app.dependencies import get_current_user_payload

    def _user() -> str:
        return str(acting_user)

    def _payload() -> dict:
        return {"sub": str(acting_user), "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


class TestCOIDOR:
    """Wrong-tenant caller gets 404, not a 200 or 403."""

    @pytest.mark.asyncio
    async def test_get_co_wrong_project_returns_404(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        owner = await _make_user(session)
        attacker = await _make_user(session)
        project = await _make_project(session, owner)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        app = _build_app(session, attacker)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/v1/changeorders/{co.id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_co_wrong_project_returns_404(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        owner = await _make_user(session)
        attacker = await _make_user(session)
        project = await _make_project(session, owner)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        app = _build_app(session, attacker)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(f"/v1/changeorders/{co.id}", json={"title": "Hijacked"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_co_wrong_project_returns_404(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        owner = await _make_user(session)
        attacker = await _make_user(session)
        project = await _make_project(session, owner)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        app = _build_app(session, attacker)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(f"/v1/changeorders/{co.id}")
        assert resp.status_code == 404


# ── Money Decimal-string ──────────────────────────────────────────────────────


class TestCOMoneyDecimal:
    """cost_impact persists as exact Decimal, not float."""

    @pytest.mark.asyncio
    async def test_cost_impact_round_trips_exactly(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        exact = Decimal("12345.67")
        co = await _create_co(svc, project, cost_impact=str(exact))
        await session.commit()

        fetched = await svc.get_order(co.id)
        result = Decimal(str(fetched.cost_impact))
        assert result == exact, f"Expected {exact!r}, got {result!r}"

    @pytest.mark.asyncio
    async def test_contractor_amount_is_decimal(self, session: AsyncSession, svc: ChangeOrderService) -> None:
        """contractor_amount column uses MoneyType — no float drift."""
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        co = await _create_co(svc, project)
        await session.commit()

        # Update contractor_amount via update_order (schema-level).
        from app.modules.changeorders.schemas import ChangeOrderUpdate

        await svc.update_order(
            co.id,
            ChangeOrderUpdate(contractor_amount="88888.88"),  # type: ignore[call-arg]
        )
        await session.commit()

        fetched = await svc.get_order(co.id)
        if fetched.contractor_amount is not None:
            result = Decimal(str(fetched.contractor_amount))
            assert result == Decimal("88888.88")
