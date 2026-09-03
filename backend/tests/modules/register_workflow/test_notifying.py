# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The bell: what this module tells the rest of the platform.

Everything it computed was pull-only - true if you were looking at the
tab, invisible if you were not. The dedupe is the load-bearing part: the
workspace polls every 45 seconds, so an un-deduplicated publish trains
everyone to ignore the bell, and an ignored bell is worse than none.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import events, notifying, service
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.fixture
def published(monkeypatch) -> list[tuple[str, dict]]:
    """Capture what would go on the bus, without a live subscriber."""
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(events, "_publish", lambda name, data: seen.append((name, data)))
    return seen


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"nt-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="NT",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"NT {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


def _yesterday() -> str:
    return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_raising_an_item_announces_it(session: AsyncSession, published) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    names = [n for n, _d in published]
    assert events.ITEM_RAISED in names
    payload = next(d for n, d in published if n == events.ITEM_RAISED)
    assert payload["reference"] == item.reference
    assert payload["project_id"] == str(pid)


@pytest.mark.asyncio
async def test_a_gate_standing_open_is_announced(session: AsyncSession, published) -> None:
    """A gate the platform never mentions is one somebody finds a week later."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    published.clear()
    # Tick up to the gate; completing the step BEFORE it leaves the gate standing.
    for s in steps:
        if s.step_type == "gate":
            break
        await service.complete_step(session, s.id, user_id="u1")
    gates = [d for n, d in published if n == events.GATE_OPEN]
    assert gates, "the gate now standing was never announced"
    assert gates[-1]["reference"] == item.reference


@pytest.mark.asyncio
async def test_an_overdue_item_is_announced_once_a_day(session: AsyncSession, published) -> None:
    """The dedupe. Polling every 45 seconds, this must not fire twice."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Late one", fields={})
    item.due_date = _yesterday()
    await session.flush()
    published.clear()

    first = await notifying.sweep_project(session, project_id=pid)
    overdue = [d for n, d in published if n == events.ITEM_OVERDUE]
    assert len(overdue) == 1
    assert overdue[0]["reference"] == item.reference
    assert overdue[0]["days_late"] >= 1
    assert first["published"] >= 1

    # The very next poll, 45 seconds later.
    published.clear()
    second = await notifying.sweep_project(session, project_id=pid)
    assert [d for n, d in published if n == events.ITEM_OVERDUE] == []
    assert second["published"] == 0


@pytest.mark.asyncio
async def test_an_item_that_is_not_late_says_nothing(session: AsyncSession, published) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Fine", fields={})
    item.due_date = (datetime.now(UTC).date() + timedelta(days=5)).isoformat()
    await session.flush()
    published.clear()
    await notifying.sweep_project(session, project_id=pid)
    assert [d for n, d in published if n == events.ITEM_OVERDUE] == []


@pytest.mark.asyncio
async def test_the_notified_memory_cannot_be_forged_by_an_edit(
    session: AsyncSession,
) -> None:
    """A client that could rewrite it could silence its own overdue notices."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    await service.update_item(
        session,
        item,
        fields={"Question": "still here", notifying.NOTIFIED_KEY: {"overdue": "2099-01-01"}},
    )
    assert not (item.fields or {}).get(notifying.NOTIFIED_KEY)


@pytest.mark.asyncio
async def test_a_failed_subscriber_never_takes_the_action_with_it(session: AsyncSession, monkeypatch) -> None:
    """Ticking a gate must not fail because the bell is broken."""

    def boom(*_a, **_k):
        raise RuntimeError("notification service is down")

    monkeypatch.setattr("app.core.events.event_bus.publish_detached", boom)
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert item.reference, "the raise survived a broken bus"
