"""Round-5 / R7 tests for the Management of Change (MoC) module.

Scope:
    * FSM allowlist: proposed -> reviewed -> accepted/declined -> implemented.
      Invalid leaps (proposed -> accepted) raise HTTP 409.
    * RBAC pins: review requires moc.review (Manager+), accept/decline requires
      moc.approve (Manager+), implement requires moc.implement (Editor+).
    * IDOR audit: GET / PATCH / DELETE on wrong-project MoC entry -> 404.
    * Audit trail: every transition writes an ActivityLog row in the same txn.
    * Money Decimal-string: cost_impact, MoCImpact.cost_impact persist as exact
      Decimal (not float).
    * Terminal states: declining or implementing locks the entry for editing.
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
from app.modules.moc.models import MoCEntry, MoCImpact
from app.modules.moc.router import router as moc_router
from app.modules.moc.schemas import MoCEntryCreate, MoCEntryUpdate, MoCImpactCreate
from app.modules.moc.service import MOC_TRANSITIONS, MoCService, allowed_moc_transitions
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS
from app.modules.users.models import APIKey, User

# ── Tables ────────────────────────────────────────────────────────────────────

_TABLES = [
    User.__table__,
    APIKey.__table__,
    Project.__table__,
    ProjectWBS.__table__,
    ProjectMilestone.__table__,
    MoCEntry.__table__,
    MoCImpact.__table__,
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
async def svc(session: AsyncSession) -> MoCService:
    return MoCService(session)


async def _make_user(session: AsyncSession) -> uuid.UUID:
    u = User(email=f"u{uuid.uuid4().hex[:8]}@test.com", hashed_password="x")
    session.add(u)
    await session.flush()
    await session.refresh(u)
    return u.id


async def _make_project(session: AsyncSession, owner: uuid.UUID) -> uuid.UUID:
    p = Project(name="MoC Test", owner_id=owner, currency="EUR")
    session.add(p)
    await session.flush()
    await session.refresh(p)
    return p.id


async def _create_entry(svc: MoCService, project_id: uuid.UUID, user_id: uuid.UUID) -> MoCEntry:
    return await svc.create_entry(
        MoCEntryCreate(
            project_id=project_id,
            title="Test MoC",
            change_category="engineering",
            risk_level="medium",
            cost_impact="5000.00",
        ),
        user_id=str(user_id),
    )


# ── FSM allowlist ──────────────────────────────────────────────────────────────


class TestMoCFSM:
    """MoC state machine — only valid transitions accepted."""

    def test_proposed_to_reviewed_allowed(self) -> None:
        assert "reviewed" in allowed_moc_transitions("proposed")

    def test_proposed_to_accepted_blocked(self) -> None:
        assert "accepted" not in allowed_moc_transitions("proposed")

    def test_proposed_to_declined_blocked(self) -> None:
        assert "declined" not in allowed_moc_transitions("proposed")

    def test_reviewed_to_accepted_allowed(self) -> None:
        assert "accepted" in allowed_moc_transitions("reviewed")

    def test_reviewed_to_declined_allowed(self) -> None:
        assert "declined" in allowed_moc_transitions("reviewed")

    def test_accepted_to_implemented_allowed(self) -> None:
        assert "implemented" in allowed_moc_transitions("accepted")

    def test_declined_is_terminal(self) -> None:
        assert allowed_moc_transitions("declined") == []

    def test_implemented_is_terminal(self) -> None:
        assert allowed_moc_transitions("implemented") == []

    def test_full_fsm_shape(self) -> None:
        for state, nexts in MOC_TRANSITIONS.items():
            assert isinstance(nexts, list), f"State {state!r} has non-list transitions"

    @pytest.mark.asyncio
    async def test_invalid_leap_raises_409(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await svc.transition(entry.id, "accepted", user_id=str(user))
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_full_lifecycle_proposed_to_implemented(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        assert entry.status == "proposed"
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user), notes="Risk OK")
        assert entry.status == "reviewed"
        assert entry.reviewed_by == str(user)
        await session.commit()

        entry = await svc.transition(entry.id, "accepted", user_id=str(user), notes="Approved")
        assert entry.status == "accepted"
        assert entry.decided_by == str(user)
        await session.commit()

        entry = await svc.transition(entry.id, "implemented", user_id=str(user))
        assert entry.status == "implemented"
        assert entry.implemented_by == str(user)
        await session.commit()

    @pytest.mark.asyncio
    async def test_full_lifecycle_proposed_to_declined(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user))
        await session.commit()

        entry = await svc.transition(entry.id, "declined", user_id=str(user), notes="Too risky")
        assert entry.status == "declined"
        await session.commit()

        # Terminal: any further transition raises 409.
        with pytest.raises(HTTPException):
            await svc.transition(entry.id, "accepted", user_id=str(user))

    @pytest.mark.asyncio
    async def test_terminal_implemented_raises_on_transition(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user))
        await session.commit()
        entry = await svc.transition(entry.id, "accepted", user_id=str(user))
        await session.commit()
        entry = await svc.transition(entry.id, "implemented", user_id=str(user))
        await session.commit()

        with pytest.raises(HTTPException):
            await svc.transition(entry.id, "proposed", user_id=str(user))


# ── Audit trail ────────────────────────────────────────────────────────────────


class TestMoCAuditTrail:
    """Every MoC FSM transition writes an ActivityLog row (same transaction)."""

    @pytest.mark.asyncio
    async def test_review_writes_audit_log(self, session: AsyncSession, svc: MoCService) -> None:
        from sqlalchemy import select

        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user), notes="OK")
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(ActivityLog)
                    .where(ActivityLog.entity_type == "moc_entry")
                    .where(ActivityLog.entity_id == str(entry.id))
                    .where(ActivityLog.to_status == "reviewed")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1
        row = rows[0]
        assert row.from_status == "proposed"
        assert row.action == "status_changed"
        assert row.reason == "OK"

    @pytest.mark.asyncio
    async def test_accept_writes_audit_log(self, session: AsyncSession, svc: MoCService) -> None:
        from sqlalchemy import select

        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user))
        await session.commit()
        entry = await svc.transition(entry.id, "accepted", user_id=str(user), notes="Sponsor OK")
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(ActivityLog)
                    .where(ActivityLog.entity_type == "moc_entry")
                    .where(ActivityLog.entity_id == str(entry.id))
                    .where(ActivityLog.to_status == "accepted")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_decline_writes_audit_log(self, session: AsyncSession, svc: MoCService) -> None:
        from sqlalchemy import select

        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user))
        await session.commit()
        entry = await svc.transition(entry.id, "declined", user_id=str(user))
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(ActivityLog)
                    .where(ActivityLog.entity_type == "moc_entry")
                    .where(ActivityLog.entity_id == str(entry.id))
                    .where(ActivityLog.to_status == "declined")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1


# ── IDOR via router ───────────────────────────────────────────────────────────


def _build_app(session_override: AsyncSession, acting_user: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(moc_router, prefix="/v1/moc")

    async def _sess() -> AsyncIterator[AsyncSession]:
        yield session_override

    from app.dependencies import get_current_user_payload

    def _user() -> str:
        return str(acting_user)

    def _payload() -> dict:
        # ``role=admin`` short-circuits RequirePermission so no separate
        # permission override is needed.
        return {"sub": str(acting_user), "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


class TestMoCIDOR:
    """Wrong-tenant caller gets 404, not the resource data."""

    @pytest.mark.asyncio
    async def test_get_entry_wrong_project_returns_404(self, session: AsyncSession, svc: MoCService) -> None:
        owner = await _make_user(session)
        attacker = await _make_user(session)
        project = await _make_project(session, owner)
        await session.commit()

        entry = await _create_entry(svc, project, owner)
        await session.commit()

        app = _build_app(session, attacker)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/v1/moc/{entry.id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_entry_wrong_project_returns_404(self, session: AsyncSession, svc: MoCService) -> None:
        owner = await _make_user(session)
        attacker = await _make_user(session)
        project = await _make_project(session, owner)
        await session.commit()

        entry = await _create_entry(svc, project, owner)
        await session.commit()

        app = _build_app(session, attacker)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(f"/v1/moc/{entry.id}", json={"title": "Hijacked"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_entry_wrong_project_returns_404(self, session: AsyncSession, svc: MoCService) -> None:
        owner = await _make_user(session)
        attacker = await _make_user(session)
        project = await _make_project(session, owner)
        await session.commit()

        entry = await _create_entry(svc, project, owner)
        await session.commit()

        app = _build_app(session, attacker)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(f"/v1/moc/{entry.id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_review_endpoint_wrong_project_returns_404(self, session: AsyncSession, svc: MoCService) -> None:
        """FSM transition endpoint also IDOR-guarded."""
        owner = await _make_user(session)
        attacker = await _make_user(session)
        project = await _make_project(session, owner)
        await session.commit()

        entry = await _create_entry(svc, project, owner)
        await session.commit()

        app = _build_app(session, attacker)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/v1/moc/{entry.id}/review", json={})
        assert resp.status_code == 404


# ── Money Decimal-string ──────────────────────────────────────────────────────


class TestMoCMoneyDecimal:
    """MoCEntry and MoCImpact money fields round-trip as exact Decimal."""

    @pytest.mark.asyncio
    async def test_entry_cost_impact_exact_decimal(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        amount = Decimal("19999.99")
        entry = await svc.create_entry(
            MoCEntryCreate(
                project_id=project,
                title="Money MoC",
                change_category="safety",
                risk_level="high",
                cost_impact=str(amount),
                currency="USD",
            ),
            user_id=str(user),
        )
        await session.commit()

        fetched = await svc.get_entry(entry.id)
        result = Decimal(str(fetched.cost_impact))
        assert result == amount, f"Expected {amount!r}, got {result!r}"

    @pytest.mark.asyncio
    async def test_impact_cost_impact_exact_decimal(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        amount = Decimal("3456.78")
        impact = await svc.add_impact(
            entry.id,
            MoCImpactCreate(
                impact_area="cost",
                severity="high",
                cost_impact=str(amount),
                currency="EUR",
            ),
        )
        await session.commit()

        fetched = await svc.get_impact(impact.id)
        result = Decimal(str(fetched.cost_impact))
        assert result == amount, f"Expected {amount!r}, got {result!r}"

    @pytest.mark.asyncio
    async def test_zero_cost_impact_stored_as_zero(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await svc.create_entry(
            MoCEntryCreate(
                project_id=project,
                title="Zero cost MoC",
                cost_impact="0",
            ),
            user_id=str(user),
        )
        await session.commit()

        fetched = await svc.get_entry(entry.id)
        assert Decimal(str(fetched.cost_impact)) == Decimal("0")


# ── Terminal state edit lock ──────────────────────────────────────────────────


class TestMoCEditLock:
    """Implemented and declined entries cannot be updated."""

    @pytest.mark.asyncio
    async def test_implemented_entry_update_raises_409(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user))
        await session.commit()
        entry = await svc.transition(entry.id, "accepted", user_id=str(user))
        await session.commit()
        entry = await svc.transition(entry.id, "implemented", user_id=str(user))
        await session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await svc.update_entry(entry.id, MoCEntryUpdate(title="Too late"))
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_declined_entry_update_raises_409(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user))
        await session.commit()
        entry = await svc.transition(entry.id, "declined", user_id=str(user))
        await session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await svc.update_entry(entry.id, MoCEntryUpdate(title="Still no"))
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_proposed_entry_delete_allowed(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        await svc.delete_entry(entry.id)  # must not raise

    @pytest.mark.asyncio
    async def test_reviewed_entry_delete_raises_409(self, session: AsyncSession, svc: MoCService) -> None:
        user = await _make_user(session)
        project = await _make_project(session, user)
        await session.commit()

        entry = await _create_entry(svc, project, user)
        await session.commit()

        entry = await svc.transition(entry.id, "reviewed", user_id=str(user))
        await session.commit()

        with pytest.raises(HTTPException):
            await svc.delete_entry(entry.id)


# ── RBAC permission coverage ──────────────────────────────────────────────────


class TestMoCPermissions:
    """Permissions module must register all required permission strings."""

    def test_register_moc_permissions_contains_approve(self) -> None:
        from app.core.permissions import permission_registry
        from app.modules.moc.permissions import register_moc_permissions

        register_moc_permissions()
        all_perms = {perm for module_perms in permission_registry._module_permissions.values() for perm in module_perms}
        assert "moc.approve" in all_perms
        assert "moc.review" in all_perms
        assert "moc.implement" in all_perms

    def test_register_moc_permissions_role_levels(self) -> None:
        from app.core.permissions import permission_registry
        from app.modules.moc.permissions import register_moc_permissions

        register_moc_permissions()
        # Verify moc.approve is registered under the moc module.
        module_perms = permission_registry.list_modules()
        assert "moc" in module_perms
        assert "moc.approve" in module_perms["moc"]
