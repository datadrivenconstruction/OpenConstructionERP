# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: presence rooms stay project scoped, academy or not (regression for E5).

App-wide presence shows who is working where, by name. A tab reports the
project it is in, and the socket only places it in that project's room when
``verify_project_access`` lets its user in; otherwise the tab is in no room and
sees nobody. Nothing was changed for the academy; this file pins that a learner
reporting another learner's project lands in no room, with the flag on and
off, and that the owner still lands in their own room.

The access check opens its own session from ``async_session_factory``, which
this lane does not bind, so it is pointed at the test session for the duration.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest

from app.modules.global_presence import router as presence
from app.modules.global_presence.hub import GlobalPresenceHub
from tests.pg.academy_isolation.rows import make_project, make_user
from tests.pg.tender_award_fixtures import _NonCommittingSession

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


class _Tab:
    """Stands in for a socket: the hub only uses it as a key."""


@pytest.mark.parametrize("academy_on", [True, False], ids=["academy_on", "academy_off"])
async def test_a_learner_reporting_another_learners_project_joins_no_room(
    pg_session, academy, monkeypatch, academy_on: bool
) -> None:
    academy(academy_on)
    monkeypatch.setattr(presence, "async_session_factory", lambda: _NonCommittingSession(pg_session))
    alice = await make_user(pg_session, name="Alice")
    bob = await make_user(pg_session, name="Bob")
    project = await make_project(pg_session, alice)

    bob_room = await presence._accessible_project(bob.id, str(project.id))
    alice_room = await presence._accessible_project(alice.id, str(project.id))
    assert bob_room is None
    assert alice_room == project.id

    hub = GlobalPresenceHub()
    alice_tab, bob_tab = _Tab(), _Tab()
    await hub.join(alice_tab, user_id=alice.id, user_name="Alice")  # type: ignore[arg-type]
    await hub.join(bob_tab, user_id=bob.id, user_name="Bob")  # type: ignore[arg-type]
    await hub.set_context(alice_tab, route="/boq", project_id=alice_room)  # type: ignore[arg-type]
    await hub.set_context(bob_tab, route="/boq", project_id=bob_room)  # type: ignore[arg-type]

    assert [e["user_id"] for e in hub.roster(project.id)] == [str(alice.id)]
    assert hub.roster(None) == []
