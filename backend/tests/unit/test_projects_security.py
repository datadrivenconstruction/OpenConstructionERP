# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Hardening tests for the ``projects`` module.

Covers the four security/correctness fixes shipped alongside this file:

1. **Slug collision race** — ``ProjectService._generate_project_code`` is
   serialised by an asyncio.Lock + post-lock collision re-check so two
   concurrent ``create_project`` calls never produce the same code
   (``Project.project_code`` has no DB-level UniqueConstraint).
2. **Currency change ramifications** — ``update_project`` rejects with
   HTTP 409 when the caller flips ``project.currency`` while BOQ
   positions already exist, unless ``metadata.allow_currency_change``
   is True (escape hatch for admins who know what they're doing).
3. **Currency-changed event** — when currency does change, a
   ``projects.project.currency_changed`` event is published so BOQ /
   rollup subscribers can react.
4. **Inactive-user member-add guard** — ``add_project_member`` rejects
   ``is_active=False`` users with HTTP 400 instead of silently creating
   a dangling membership row.

All tests run against an isolated, throwaway PostgreSQL database (cloned from a
schema-loaded template by ``tests._pg.isolated_engine``) so they run fast and
never touch the production database. The fixtures open several independent
sessions from a shared sessionmaker and rely on cross-connection commit
visibility (the concurrent-create test in particular spins up 50 separately
committing sessions), so a real throwaway engine is used rather than a single
savepoint-rolled-back session.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from tests._pg import isolated_engine


@pytest_asyncio.fixture
async def engine_factory():
    """Per-test throwaway PostgreSQL database + ORM sessionmaker."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        yield engine, factory


@pytest_asyncio.fixture
async def seeded_owner(engine_factory) -> tuple[uuid.UUID, Any]:
    """Create an owner User row so Project.owner_id FK is satisfied."""
    _engine, factory = engine_factory
    from app.modules.users.models import User

    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"sec-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x" * 60,
                full_name="Sec Owner",
                role="estimator",
                locale="en",
                is_active=True,
                metadata_={},
            )
        )
        await session.commit()
    return user_id, factory


def _settings_stub() -> Any:
    """Minimal Settings double — service only reads .settings as an attribute."""

    class _S:
        pass

    return _S()


# ── 1. Slug collision race ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_create_yields_distinct_project_codes(
    seeded_owner,
) -> None:
    """50 concurrent create_project calls must all get unique project_codes.

    Without the asyncio.Lock + post-lock recheck in
    ``_generate_project_code``, ``max_seq + 1`` would collapse to the
    same value for every concurrent task and the resulting projects would
    all share one ``project_code`` — which downstream code keys off as
    if it were unique.
    """
    owner_id, factory = seeded_owner
    from app.modules.projects.schemas import ProjectCreate
    from app.modules.projects.service import ProjectService

    async def _one_create(i: int) -> str | None:
        async with factory() as session:
            svc = ProjectService(session, _settings_stub())
            proj = await svc.create_project(
                ProjectCreate(name=f"Concurrent {i}"),
                owner_id,
            )
            await session.commit()
            return proj.project_code

    codes = await asyncio.gather(*[_one_create(i) for i in range(50)])
    assert all(codes), "every create must yield a non-empty project_code"
    # The whole point: no two creates collided on the same generated code.
    assert len(set(codes)) == len(codes), f"duplicate project_code in {codes}"


# ── 2. Currency change blocked when BOQ positions exist ─────────────────


@pytest.mark.asyncio
async def test_currency_change_blocked_when_positions_exist(
    seeded_owner,
) -> None:
    """PATCH project.currency must 409 while BOQ positions still reference it.

    Silently flipping EUR → USD on a project that already has positions
    priced in EUR corrupts every rollup downstream (BOQ totals, exports,
    reporting). The service raises HTTP 409 and refuses the change.
    """
    owner_id, factory = seeded_owner
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
    from app.modules.projects.service import ProjectService

    async with factory() as session:
        svc = ProjectService(session, _settings_stub())
        proj = await svc.create_project(
            ProjectCreate(name="With BOQ", currency="EUR"),
            owner_id,
        )
        # Seed one BOQ with one position so the guard trips.
        boq = BOQ(project_id=proj.id, name="Main")
        session.add(boq)
        await session.flush()
        session.add(
            Position(
                boq_id=boq.id,
                ordinal="01.001",
                description="Test",
                unit="m3",
                quantity="10",
                unit_rate="100",
            )
        )
        await session.commit()
        project_id = proj.id

    # Real currency change — must 409.
    async with factory() as session:
        svc = ProjectService(session, _settings_stub())
        with pytest.raises(HTTPException) as exc_info:
            await svc.update_project(
                project_id,
                ProjectUpdate(currency="USD"),
            )
        assert exc_info.value.status_code == 409
        assert "currency" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_currency_change_allowed_with_metadata_override(
    seeded_owner,
) -> None:
    """``metadata.allow_currency_change=True`` is the documented escape hatch.

    An admin who has manually reconciled BOQ rates can opt in to the
    change and the service performs it (and emits the
    ``currency_changed`` event for subscribers).
    """
    owner_id, factory = seeded_owner
    from app.core.events import event_bus
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
    from app.modules.projects.service import ProjectService

    async with factory() as session:
        svc = ProjectService(session, _settings_stub())
        proj = await svc.create_project(
            ProjectCreate(name="Override", currency="EUR"),
            owner_id,
        )
        boq = BOQ(project_id=proj.id, name="Main")
        session.add(boq)
        await session.flush()
        session.add(
            Position(
                boq_id=boq.id,
                ordinal="01.001",
                description="Test",
                unit="m3",
                quantity="10",
                unit_rate="100",
            )
        )
        await session.commit()
        project_id = proj.id

    # Subscribe to currency_changed before the update fires. Sync handler
    # so conftest's ``_sync_publish_detached`` can drive the publish to
    # completion via ``coro.send(None)`` without the loop yielding — the
    # EventBus awaits a sync handler via ``asyncio.to_thread`` which
    # finishes within the same task tick.
    received: list[dict[str, Any]] = []

    def _on_currency_changed(event: Any) -> None:
        # EventBus emits an Event object; data is on .data
        data = getattr(event, "data", event)
        received.append(data if isinstance(data, dict) else {"raw": data})

    event_bus.subscribe("projects.project.currency_changed", _on_currency_changed)

    try:
        async with factory() as session:
            svc = ProjectService(session, _settings_stub())
            updated = await svc.update_project(
                project_id,
                ProjectUpdate(
                    currency="USD",
                    metadata={"allow_currency_change": True},
                ),
            )
            await session.commit()

        # ``publish_detached`` schedules subscriber callbacks on the loop;
        # give them a few ticks to run before asserting. The conftest's
        # sync shim drives the publish coroutine but any subscriber that
        # yields (sync handlers wrapped in ``asyncio.to_thread``,
        # ``ensure_future`` fallbacks) needs the loop to step.
        for _ in range(10):
            await asyncio.sleep(0)

        # Whichever shape the event bus passed through, the dedicated
        # currency-changed event must have fired at least once.
        assert updated.currency == "USD"
        assert len(received) >= 1, f"expected >=1 event, got {received}"
        payload = received[0]
        assert payload.get("from_currency") == "EUR"
        assert payload.get("to_currency") == "USD"
    finally:
        # Detach the test subscriber so it doesn't leak into other tests
        # in the same session.
        try:
            event_bus.unsubscribe(
                "projects.project.currency_changed",
                _on_currency_changed,
            )
        except Exception:
            pass


@pytest.mark.asyncio
async def test_currency_change_allowed_without_positions(seeded_owner) -> None:
    """A fresh project (no BOQ positions yet) accepts a currency change.

    Catches the false-positive case where the guard incorrectly blocks
    early-stage projects whose currency the user is still figuring out.
    """
    owner_id, factory = seeded_owner
    from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
    from app.modules.projects.service import ProjectService

    async with factory() as session:
        svc = ProjectService(session, _settings_stub())
        proj = await svc.create_project(
            ProjectCreate(name="No BOQ Yet", currency="EUR"),
            owner_id,
        )
        await session.commit()
        project_id = proj.id

    async with factory() as session:
        svc = ProjectService(session, _settings_stub())
        updated = await svc.update_project(
            project_id,
            ProjectUpdate(currency="GBP"),
        )
        await session.commit()
        assert updated.currency == "GBP"


# ── 3. Inactive-user member-add guard ───────────────────────────────────


@pytest.mark.asyncio
async def test_add_project_member_rejects_inactive_user(seeded_owner) -> None:
    """``add_project_member`` must 400 when invitee.is_active is False.

    A deactivated user can't log in, but the prior code happily added
    them to the project's Default Team — leaving a dangling membership
    row the admin UI then had to garbage-collect.
    """
    owner_id, factory = seeded_owner
    from app.modules.projects.member_schemas import AddProjectMemberRequest
    from app.modules.projects.member_service import add_project_member
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    inactive_id = uuid.uuid4()
    project_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=inactive_id,
                email=f"inactive-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x" * 60,
                full_name="Inactive User",
                role="estimator",
                locale="en",
                is_active=False,
                metadata_={},
            )
        )
        session.add(
            Project(
                id=project_id,
                name="Members Sec",
                owner_id=owner_id,
                status="active",
            )
        )
        await session.commit()

    async with factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await add_project_member(
                session,
                project_id,
                AddProjectMemberRequest(user_id=inactive_id, role="viewer"),
            )
        assert exc_info.value.status_code == 400
        assert "deactivat" in exc_info.value.detail.lower()
