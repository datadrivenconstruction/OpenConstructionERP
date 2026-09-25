# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The presence hub keeps each project's room to itself.

It used to be one room for the whole server, so a tab saw every signed-in
account and the page each was on. The router decides which project a tab may
be in; this file covers what the hub does with that: a broadcast reaches only
the tabs in the same project, a roster lists only the people there, and a
user's page elsewhere never shows up in it.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.global_presence.hub import GlobalPresenceHub


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


P_A = uuid.uuid4()
P_B = uuid.uuid4()


@pytest.mark.asyncio
async def test_a_broadcast_reaches_only_its_project() -> None:
    hub = GlobalPresenceHub()
    alice, bob = uuid.uuid4(), uuid.uuid4()
    a_ws, b_ws = _Socket(), _Socket()
    await hub.join(a_ws, user_id=alice, user_name="Alice")
    await hub.join(b_ws, user_id=bob, user_name="Bob")
    await hub.set_context(a_ws, route="/boq", project_id=P_A)
    await hub.set_context(b_ws, route="/boq", project_id=P_B)

    await hub.broadcast(P_B, {"event": "presence_update", "user_id": str(bob)})

    assert a_ws.sent == []
    assert b_ws.sent == [{"event": "presence_update", "user_id": str(bob)}]
    assert [e["user_id"] for e in hub.roster(P_A)] == [str(alice)]
    assert [e["user_id"] for e in hub.roster(P_B)] == [str(bob)]


@pytest.mark.asyncio
async def test_a_tab_in_no_project_sees_and_is_seen_by_nobody() -> None:
    hub = GlobalPresenceHub()
    alice = uuid.uuid4()
    a_ws = _Socket()
    await hub.join(a_ws, user_id=alice, user_name="Alice")

    assert hub.roster(None) == []
    assert await hub.broadcast(None, {"event": "presence_update"}) == 0
    assert hub.roster(P_A) == []


@pytest.mark.asyncio
async def test_a_second_tab_elsewhere_does_not_leak_its_page() -> None:
    hub = GlobalPresenceHub()
    alice = uuid.uuid4()
    here, elsewhere = _Socket(), _Socket()
    await hub.join(here, user_id=alice, user_name="Alice")
    await hub.join(elsewhere, user_id=alice, user_name="Alice")
    await hub.set_context(here, route="/boq", project_id=P_A)
    change = await hub.set_context(elsewhere, route="/secret-page", project_id=P_B)

    assert change is not None and change.entered and not change.left
    assert [e["route"] for e in hub.roster(P_A)] == ["/boq"]


@pytest.mark.asyncio
async def test_leaving_a_project_is_reported_only_for_the_last_tab_there() -> None:
    hub = GlobalPresenceHub()
    alice = uuid.uuid4()
    one, two = _Socket(), _Socket()
    await hub.join(one, user_id=alice, user_name="Alice")
    await hub.join(two, user_id=alice, user_name="Alice")
    await hub.set_context(one, route="/a", project_id=P_A)
    second = await hub.set_context(two, route="/b", project_id=P_A)
    assert second is not None and not second.entered

    moved = await hub.set_context(one, route="/c", project_id=P_B)
    assert moved is not None and not moved.left and moved.entered

    gone = await hub.leave(two)
    assert gone is not None and gone.project_id == P_A and gone.left_project
    assert hub.roster(P_A) == []
