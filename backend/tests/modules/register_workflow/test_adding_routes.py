# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Adding a decision to a workflow that has already started.

Routes were stripped from the action library and refused by both the
service and the request schema, so a job that hit a SECOND fork could not
be modelled: it degraded to flat steps and lost the branch record, which
is the one thing a decision exists to keep.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import service, templates
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"ar-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="AR",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"AR {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


def test_the_action_library_offers_decisions() -> None:
    """They were filtered out, so nothing could ever add one."""
    for kind in templates.KINDS:
        actions = templates.actions_for(kind)
        if not any(s["t"] == "route" for s in templates.FLOWS.get(kind, [])):
            continue
        routes = [a for a in actions if a["t"] == "route"]
        assert routes, f"{kind} offers no decision in its action library"
        assert all(a.get("branches") for a in routes), "a decision arrived with no paths"


@pytest.mark.asyncio
async def test_a_second_decision_can_be_added(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    spine_route = next(s for s in item.steps if s.step_type == "route")

    added = await service.add_step(
        session,
        item.id,
        name="Does the client accept the cost?",
        step_type="route",
        branches={"Accepted": ["Raise the order"], "Rejected": ["Advise the client in writing"]},
    )
    assert added.step_type == "route"
    assert set(added.branches) == {"Accepted", "Rejected"}
    # And the spine's own decision is untouched.
    assert spine_route.branches


@pytest.mark.asyncio
async def test_a_decision_with_no_paths_is_refused(session: AsyncSession) -> None:
    """It would render a fork whose picker is empty and which nothing can
    ever get past - a dead end wearing a decision's clothes."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    with pytest.raises(service.WorkflowError, match="needs the paths"):
        await service.add_step(session, item.id, name="Which way?", step_type="route")


@pytest.mark.asyncio
async def test_an_added_decision_can_actually_be_taken(session: AsyncSession) -> None:
    """The point of adding one: it forks, and the branch's steps appear."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="toolbox", title="T", fields={})
    added = await service.add_step(
        session,
        item.id,
        name="Anyone need a re-brief?",
        step_type="route",
        branches={"No": [], "Yes": ["Re-brief delivered", "Second sign-on collected"]},
        after_position=max(s.position for s in item.steps),
    )
    # Walk the spine up to it. EVERY open step before the fork, gates
    # included - the toolbox spine carries one, and skipping it left the
    # route unreachable behind an open step.
    for s in sorted(item.steps, key=lambda x: x.position):
        if s.position >= added.position:
            break
        if s.state == "open":
            await service.complete_step(session, s.id, user_id="u1")

    before = len(item.steps)
    await service.take_route(session, added.id, "Yes", user_id="u1")
    assert added.chosen_branch == "Yes"
    assert len(item.steps) == before + 2
    assert "Re-brief delivered" in [s.name for s in item.steps]


@pytest.mark.asyncio
async def test_a_new_action_lands_after_the_step_you_are_standing_on(
    session: AsyncSession,
) -> None:
    """Sending no position put every added action BEFORE the current step
    - the one place it never belongs."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    await service.complete_step(session, steps[0].id, user_id="u1")
    current = next(s for s in sorted(item.steps, key=lambda x: x.position) if s.state == "open")

    added = await service.add_step(session, item.id, name="Chased by phone", after_position=current.position)
    assert added.position == current.position + 1
    ordered = sorted(item.steps, key=lambda s: s.position)
    assert ordered[ordered.index(current) + 1].name == "Chased by phone"
