# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the project governance PostgreSQL tests.

A world is a throwaway database with real users, a project, team membership,
an approval route for ``phase_gate`` and ``frame_change`` whose single step
names the decider, CDE containers with revisions, and the shipped ``neutral``
catalogue pinned. Everything commits for real, so locks and subscribers behave
as they do in production.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.project_governance import evaluator as ev
from app.modules.project_governance import evidence as evidence_registry
from app.modules.project_governance.errors import GovernanceError
from app.modules.project_governance.models import GovernanceArea, GovernanceDocument, GovernanceGate
from app.modules.project_governance.service import GovernanceService


@contextmanager
def only_evidence(*keep: str, register: Callable[[], Any] | None = None) -> Iterator[None]:
    """Gate evidence of the named providers alone, and the registry as it was afterwards.

    The evidence registry is one per process. With every module installed, the
    blocking providers of the other modules answer ``not_met`` for a world that
    has none of their rows, and a gate a test needs to pass is refused for a
    reason that is not the test's. Inside this block only the wanted providers
    answer; on leaving it the registry (and the table of evidence links) is
    exactly what it was, also when the test failed.

    Args:
        *keep: What stays registered. Each word is matched against a
            provider's name and against the area code or kind it registered
            for, so ``"procurement"`` keeps every provider of that area and
            ``"permits_due"`` keeps the one of that name. No word keeps nothing.
        register: Called once the registry holds only ``keep``, for a module
            whose providers are not registered yet in this process, for
            example ``register=register_gate_evidence``. Whatever it registers
            is removed again on leaving.

    Usage::

        with only_evidence("delivery_model"):
            await decide(world, gate, "go")

        @pytest.fixture(autouse=True)
        def _own_evidence():
            with only_evidence(register=register_gate_evidence):
                yield
    """
    providers = dict(evidence_registry._REGISTRY)
    links = dict(evidence_registry._LINK_ROUTES)
    wanted = set(keep)
    evidence_registry._REGISTRY.clear()
    evidence_registry._REGISTRY.update({n: p for n, p in providers.items() if n in wanted or p.key in wanted})
    try:
        if register is not None:
            register()
        yield
    finally:
        evidence_registry._REGISTRY.clear()
        evidence_registry._REGISTRY.update(providers)
        evidence_registry._LINK_ROUTES.clear()
        evidence_registry._LINK_ROUTES.update(links)


@pytest.fixture
def no_foreign_evidence() -> Iterator[None]:
    """The fixture form of :func:`only_evidence` with nothing kept: an empty registry for one test.

    Import it into the test module (``from tests.pg.governance_fixtures import
    no_foreign_evidence  # noqa: F401``) and name it in the test, or in
    ``pytestmark = pytest.mark.usefixtures("no_foreign_evidence")``. A test
    that needs its own providers registers them inside; they are gone afterwards.
    """
    with only_evidence():
        yield


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    decider: uuid.UUID
    owner: uuid.UUID
    editor: uuid.UUID
    outsider: uuid.UUID
    gate_route_id: uuid.UUID | None = None
    change_route_id: uuid.UUID | None = None
    containers: dict[str, uuid.UUID] = field(default_factory=dict)


async def add_user(session: AsyncSession, role: str) -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(
        User(
            id=uid,
            email=f"{role}-{uid.hex[:8]}@example.test",
            hashed_password="x",
            full_name=f"Test {role}",
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    return uid


async def add_project(session: AsyncSession, owner: uuid.UUID, members: list[uuid.UUID]) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership

    pid = uuid.uuid4()
    session.add(
        Project(id=pid, name=f"Gov {pid.hex[:6]}", currency="EUR", status="active", owner_id=owner, metadata_={})
    )
    await session.flush()
    team = Team(project_id=pid, name="Core")
    session.add(team)
    await session.flush()
    for m in members:
        session.add(TeamMembership(team_id=team.id, user_id=m))
    await session.flush()
    return pid


async def add_route(session: AsyncSession, project_id: uuid.UUID, kind: str, approver: uuid.UUID) -> uuid.UUID:
    from app.modules.approval_routes.models import Route, Step

    route = Route(project_id=project_id, name=f"{kind} sign-off", target_kind=kind, is_active=True)
    session.add(route)
    await session.flush()
    session.add(Step(route_id=route.id, ordinal=1, approver_user_id=approver, mode="any"))
    await session.flush()
    return route.id


async def add_revision(session: AsyncSession, container_id: uuid.UUID, number: int, digest: str) -> uuid.UUID:
    from app.modules.cde.models import DocumentContainer, DocumentRevision

    rev = DocumentRevision(
        container_id=container_id,
        revision_code=f"P{number:02d}",
        revision_number=number,
        content_hash=digest,
        file_name=f"doc-{number}.pdf",
    )
    session.add(rev)
    await session.flush()
    container = await session.get(DocumentContainer, container_id)
    container.current_revision_id = rev.id
    await session.flush()
    return rev.id


async def add_container(session: AsyncSession, project_id: uuid.UUID, code: str) -> uuid.UUID:
    from app.modules.cde.models import DocumentContainer

    c = DocumentContainer(project_id=project_id, container_code=code, title=code, cde_state="wip")
    session.add(c)
    await session.flush()
    await add_revision(session, c.id, 1, f"{code}-hash-1")
    return c.id


async def build_world(
    factory: async_sessionmaker[AsyncSession], *, routes: bool = True, catalogue_id: str = "neutral"
) -> World:
    async with factory() as s:
        manager = await add_user(s, "manager")
        decider = await add_user(s, "manager")
        owner = await add_user(s, "editor")
        editor = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [decider, owner, editor])
        w = World(factory, pid, manager, decider, owner, editor, outsider)
        if routes:
            w.gate_route_id = await add_route(s, pid, "phase_gate", decider)
            w.change_route_id = await add_route(s, pid, "frame_change", decider)
        for code in ("business_case", "project_handbook", "requirements_brief"):
            w.containers[code] = await add_container(s, pid, code)
        svc = GovernanceService(s)
        await svc.set_model(
            pid,
            source="shipped",
            catalogue_id=catalogue_id,
            version=None,
            four_eyes=True,
            actor_id=manager,
            tenant_id=str(manager),
        )
        if routes:
            # Governance reads only a pinned route; nothing is found by project or kind.
            await svc.update_settings(
                pid,
                four_eyes=None,
                decision_route_id=w.gate_route_id,
                change_route_id=w.change_route_id,
                fields_set={"decision_route_id", "change_route_id"},
                actor_id=manager,
            )
        await s.commit()
    return w


async def gate(w: World, code: str) -> GovernanceGate:
    async with w.factory() as s:
        return (
            await s.execute(
                select(GovernanceGate).where(GovernanceGate.project_id == w.project_id, GovernanceGate.code == code)
            )
        ).scalar_one()


async def areas(w: World) -> dict[str, GovernanceArea]:
    async with w.factory() as s:
        return {a.code: a for a in await GovernanceService(s).repo.list_areas(w.project_id)}


async def documents(w: World) -> dict[str, GovernanceDocument]:
    async with w.factory() as s:
        return {d.doc_type: d for d in await GovernanceService(s).repo.list_documents(w.project_id)}


async def prepare_gate(
    w: World, gate_code: str, *, owner: uuid.UUID | None = None, submit: bool = True
) -> GovernanceGate:
    """Owners on every area, required documents attached and submitted, checks ready, gate in review."""
    owner = owner or w.owner
    async with w.factory() as s:
        svc = GovernanceService(s)
        for a in await svc.repo.list_areas(w.project_id):
            await svc.update_area(w.project_id, a.id, changes={"owner_user_id": owner}, actor_id=w.manager)
        g = (
            await s.execute(
                select(GovernanceGate).where(
                    GovernanceGate.project_id == w.project_id, GovernanceGate.code == gate_code
                )
            )
        ).scalar_one()
        for d in await svc.repo.list_documents(w.project_id):
            if gate_code in d.required_at_gates and d.status == "draft":
                await svc.attach_container(w.project_id, d.id, container_id=w.containers[d.doc_type], actor_id=owner)
                await svc.submit_document(w.project_id, d.id, actor_id=owner)
        await svc.start_preparation(w.project_id, g.id, actor_id=owner) if g.status == "not_started" else None
        for a in await svc.repo.list_areas(w.project_id):
            await svc.confirm_check(w.project_id, g.id, a.id, status="ready", rag="green", note="", actor_id=owner)
        if submit:
            await svc.submit_gate(w.project_id, g.id, actor_id=owner)
        await s.commit()
        return g


async def decide(
    w: World,
    gate_id: uuid.UUID,
    outcome: str = "go",
    *,
    decider: uuid.UUID | None = None,
    today: date = date(2026, 10, 11),
    **kw,
):
    async with w.factory() as s:
        # Module providers are registered on an integrated branch; one that cannot answer here
        # is named, as the dialog would, unless the test says what it acknowledges.
        seen = kw.pop("acknowledged_evidence", None)
        if seen is None:
            seen = await GovernanceService(s).unknown_evidence(w.project_id, gate_id, today=today)
        req = ev.DecisionRequest(
            outcome=outcome,
            rationale=kw.pop("rationale", "" if outcome == "go" else "reason"),
            decider_id=str(decider or w.decider),
            acknowledged_evidence=tuple(seen),
            **kw,
        )
        try:
            d = await GovernanceService(s).decide(
                w.project_id, gate_id, request=req, decider_id=decider or w.decider, role="manager", today=today
            )
        except GovernanceError as exc:
            # Name what was refused: a bare code hides which evidence or rule stopped the decision.
            exc.add_note(f"decision refused: {exc.code} {exc.violations}")
            raise
        await s.commit()
        return d


# ── HTTP ──

API = "/api/v1/project-governance"


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    """The governance router over HTTP as one user; every request commits like the real session dependency."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.project_governance.router import router

    app = FastAPI()
    app.include_router(router, prefix=API)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user_id), "role": role, "permissions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gov-test") as c:
        yield c


def project_url(w: World) -> str:
    return f"{API}/projects/{w.project_id}"


async def add_role_route(session: AsyncSession, project_id: uuid.UUID, kind: str, role: str, mode: str) -> uuid.UUID:
    """A route whose single step is held by a role, not a named user."""
    from app.modules.approval_routes.models import Route, Step

    route = Route(project_id=project_id, name=f"{kind} by {role}", target_kind=kind, is_active=True)
    session.add(route)
    await session.flush()
    session.add(Step(route_id=route.id, ordinal=1, approver_role=role, mode=mode))
    await session.flush()
    return route.id


async def add_activity(session: AsyncSession, project_id: uuid.UUID, name: str, day: str) -> uuid.UUID:
    """A milestone in a schedule of the project, on ``day`` (ISO)."""
    from app.modules.schedule.models import Activity, Schedule

    schedule = Schedule(project_id=project_id, name=f"Master {uuid.uuid4().hex[:6]}")
    session.add(schedule)
    await session.flush()
    activity = Activity(schedule_id=schedule.id, name=name, start_date=day, end_date=day, activity_type="milestone")
    session.add(activity)
    await session.flush()
    return activity.id
