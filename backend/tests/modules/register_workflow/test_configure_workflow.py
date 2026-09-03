# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The structured workflow editor's contract with ``configure_steps``.

The editor sends the whole to-do list back in one call. What that call
may and may not do is pinned here: it can ADD a decision (with its
paths), it must keep a decision it was handed, and it cannot drop a
hold point without a written reason.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import service
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"cw-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CW",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"CW {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code="25406",
    )
    session.add(proj)
    await session.flush()
    return proj.id


def _open(item) -> list:
    return [s for s in sorted(item.steps, key=lambda s: s.position) if s.state == "open"]


def _entries(steps) -> list[dict]:
    return [{"name": s.name, "type": s.step_type, "owner": s.owner or ""} for s in steps]


NEW_ROUTE = "Does Acme Electrical accept the revised price?"
NEW_BRANCHES = {
    "Accepted": ["Raise the order"],
    "Rejected": ["Advise the client in writing", "Closed out"],
}


@pytest.mark.asyncio
async def test_a_new_decision_lands_where_it_was_put_with_its_paths(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    before = _entries(_open(item))

    # Slot it in third.
    remaining = before[:2] + [{"name": NEW_ROUTE, "type": "route", "branches": NEW_BRANCHES}] + before[2:]
    await service.configure_steps(session, item.id, remaining, user_id="u1")

    after = _open(item)
    assert [s.name for s in after][:3] == [before[0]["name"], before[1]["name"], NEW_ROUTE]
    added = after[2]
    assert added.step_type == "route"
    assert added.branches == NEW_BRANCHES
    # Positions run contiguously after the new fork - nothing is stacked.
    assert [s.position for s in after] == list(range(after[0].position, after[0].position + len(after)))


@pytest.mark.asyncio
async def test_a_new_decision_without_paths_is_refused(session: AsyncSession) -> None:
    """A fork with no paths is a dead end; the whole rewrite is refused
    and the item is exactly as it was."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    before = [(s.name, s.step_type) for s in _open(item)]

    for bad in ({}, None, [], "Accepted"):
        entry: dict = {"name": NEW_ROUTE, "type": "route"}
        if bad is not None:
            entry["branches"] = bad
        with pytest.raises(service.WorkflowError, match="at least one path"):
            await service.configure_steps(session, item.id, _entries(_open(item)) + [entry])
    assert [(s.name, s.step_type) for s in _open(item)] == before


@pytest.mark.asyncio
async def test_a_kept_decision_keeps_its_paths_through_a_reorder(session: AsyncSession) -> None:
    """Listing an existing route - even typed as a plain step, with
    branches it never had - moves it and changes nothing else."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    route = next(s for s in item.steps if s.step_type == "route")
    original = dict(route.branches)

    entries = _entries(_open(item))
    idx = next(i for i, e in enumerate(entries) if e["name"] == route.name)
    moved = entries.pop(idx)
    # The editor sends the kept row's type; a client sending junk for it
    # must not be able to retype the fork or swap its paths.
    moved = {**moved, "type": "step", "branches": {"Nonsense": ["x"]}}
    entries.insert(0, moved)
    await service.configure_steps(session, item.id, entries, user_id="u1")

    after = _open(item)
    assert after[0].name == route.name
    assert after[0].step_type == "route"
    assert after[0].branches == original
    assert sum(1 for s in item.steps if s.step_type == "route") == 1


@pytest.mark.asyncio
async def test_a_gate_dropped_without_a_reason_is_refused(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    gate = next(s for s in item.steps if s.step_type == "gate")
    without = [e for e in _entries(_open(item)) if e["name"] != gate.name]

    with pytest.raises(service.WorkflowError, match="written reason"):
        await service.configure_steps(session, item.id, without)
    with pytest.raises(service.WorkflowError, match="written reason"):
        await service.configure_steps(session, item.id, without, retire_reason="   ")
    # A way of typing nothing is not a reason either.
    with pytest.raises(service.WorkflowError, match="not a reason"):
        await service.configure_steps(session, item.id, without, retire_reason="n/a")

    still = next(s for s in item.steps if s.name == gate.name)
    assert still.state == "open"


@pytest.mark.asyncio
async def test_a_gate_dropped_with_a_reason_is_retired_on_the_record(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = _open(item)
    await service.complete_step(session, steps[0].id, user_id="u1")
    gate = next(s for s in item.steps if s.step_type == "gate")
    without = [e for e in _entries(_open(item)) if e["name"] != gate.name]
    reason = "The client issues this RFI direct - there is no internal review on job 25406"

    await service.configure_steps(session, item.id, without, retire_reason=reason, user_id="u2")

    retired = next(s for s in item.steps if s.name == gate.name)
    assert retired.step_type == "gate"
    assert retired.state == "not_required"
    assert retired.override_reason == f"Taken off this workflow: {reason}"
    assert retired.completed_by == "u2"
    assert retired.completed_at
    # History first, in order; the retired hold point sits with it.
    ordered = sorted(item.steps, key=lambda s: s.position)
    assert [s.state for s in ordered][:2] == ["done", "not_required"]
    assert [s.name for s in ordered if s.state == "open"] == [e["name"] for e in without]
    assert steps[0].state == "done" and steps[0].completed_by == "u1"
