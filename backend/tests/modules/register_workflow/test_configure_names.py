# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Names in a ``configure_steps`` payload: the rails the editor enforces
client-side, enforced again where it counts.

Steps are matched BY NAME. The structured editor refuses an empty name
and two names that differ only by case; a client that is not the editor
must meet the same wall, or the rail lives in one place only.
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
        email=f"cn-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CN",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"CN {uuid.uuid4().hex[:6]}",
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


@pytest.mark.asyncio
async def test_a_blank_name_is_refused_not_silently_dropped(session: AsyncSession) -> None:
    """Eight rows sent, seven landing, no word said - that was the old
    behaviour. Now the payload is refused and the item is untouched."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    before = [s.name for s in _open(item)]

    for blank in ("", "   ", None):
        with pytest.raises(service.WorkflowError, match="needs a name"):
            await service.configure_steps(session, item.id, _entries(_open(item)) + [{"name": blank, "type": "step"}])
    assert [s.name for s in _open(item)] == before


@pytest.mark.asyncio
async def test_names_differing_only_by_case_are_refused(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    before = [s.name for s in _open(item)]
    first = before[0]

    # Two new rows, one a case-variant of the other.
    with pytest.raises(service.WorkflowError, match="differ only by case"):
        await service.configure_steps(
            session,
            item.id,
            _entries(_open(item)) + [{"name": "Send it", "type": "step"}, {"name": "send it", "type": "step"}],
        )
    # A new row that is a case-variant of a step already on the list.
    with pytest.raises(service.WorkflowError, match="differ only by case"):
        await service.configure_steps(
            session, item.id, _entries(_open(item)) + [{"name": first.upper(), "type": "step"}]
        )
    assert [s.name for s in _open(item)] == before


@pytest.mark.asyncio
async def test_a_genuine_repeat_of_the_same_name_is_still_allowed(session: AsyncSession) -> None:
    """ "Chased by phone" twice is a real workflow; only the case-variant
    is a typo."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    entries = _entries(_open(item)) + [
        {"name": "Chased by phone", "type": "step"},
        {"name": "Chased by phone", "type": "step"},
    ]
    await service.configure_steps(session, item.id, entries, user_id="u1")
    assert [s.name for s in _open(item)].count("Chased by phone") == 2
