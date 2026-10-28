# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - collaboration-locks presence hub and expiry sweeper.

``collaboration_locks`` shipped with no tests, and it is a concurrency surface:
without a test we simply do not know whether it works. These two files are the
part that needs no database. The hub is in-memory pub/sub for the presence
WebSocket; the sweeper is the loop that prunes expired locks.

Two contracts here are worth stating up front, because both are easy to break
from a different file:

* :meth:`PresenceHub.leave` decides who is still in the room by reading a
  ``_collab_lock_user_id`` attribute off every remaining socket. Nothing in the
  hub sets it -- the router does, at the point it accepts the connection. If
  that assignment is ever dropped, everyone silently disappears from the roster
  on the next leave, with no error anywhere.
* The sweeper publishes its ``collab.lock.expired`` events only after the delete
  commits, so a subscriber never reacts to a removal that was rolled back.

No database, no real sockets.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.collaboration_locks import sweeper as sweeper_mod
from app.modules.collaboration_locks.presence_hub import PresenceHub

ENTITY = "boq"
KEY = (ENTITY, uuid.uuid4())
USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


class _FakeWS:
    """The slice of ``WebSocket`` the hub touches: ``send_json`` and identity."""

    def __init__(self, *, user_id: uuid.UUID | None = None, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail
        if user_id is not None:
            # Set by the router when the connection is accepted; ``leave``
            # reads it back to work out who is still in the room.
            self._collab_lock_user_id = user_id

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("socket closed without a close frame")
        self.sent.append(payload)


@pytest.fixture
def hub() -> PresenceHub:
    return PresenceHub()


class TestJoin:
    async def test_joining_returns_a_roster_containing_the_joiner(self, hub: PresenceHub) -> None:
        """The first render must not need a second round-trip."""
        roster = await hub.join(KEY, _FakeWS(user_id=USER_A), user_id=USER_A, user_name="Ann")
        assert roster == [{"user_id": str(USER_A), "user_name": "Ann"}]
        assert hub.subscriber_count(KEY) == 1

    async def test_a_second_user_sees_both(self, hub: PresenceHub) -> None:
        await hub.join(KEY, _FakeWS(user_id=USER_A), user_id=USER_A, user_name="Ann")
        roster = await hub.join(KEY, _FakeWS(user_id=USER_B), user_id=USER_B, user_name="Ben")
        assert {entry["user_id"] for entry in roster} == {str(USER_A), str(USER_B)}
        assert hub.subscriber_count(KEY) == 2

    async def test_a_second_tab_is_another_socket_but_not_another_user(self, hub: PresenceHub) -> None:
        await hub.join(KEY, _FakeWS(user_id=USER_A), user_id=USER_A, user_name="Ann")
        roster = await hub.join(KEY, _FakeWS(user_id=USER_A), user_id=USER_A, user_name="Ann")
        assert roster == [{"user_id": str(USER_A), "user_name": "Ann"}]
        assert hub.subscriber_count(KEY) == 2

    async def test_keys_are_isolated(self, hub: PresenceHub) -> None:
        other = (ENTITY, uuid.uuid4())
        await hub.join(KEY, _FakeWS(user_id=USER_A), user_id=USER_A, user_name="Ann")
        assert hub.subscriber_count(other) == 0
        assert hub.roster(other) == []

    def test_an_unknown_key_is_empty_rather_than_an_error(self, hub: PresenceHub) -> None:
        assert hub.subscriber_count(("boq", uuid.uuid4())) == 0
        assert hub.roster(("boq", uuid.uuid4())) == []


class TestLeave:
    async def test_the_last_socket_leaving_reports_the_user_and_frees_the_key(self, hub: PresenceHub) -> None:
        ws = _FakeWS(user_id=USER_A)
        await hub.join(KEY, ws, user_id=USER_A, user_name="Ann")
        assert await hub.leave(KEY, ws) == [USER_A]
        # The key is dropped so memory does not grow as users browse entities.
        assert hub.subscriber_count(KEY) == 0
        assert hub.roster(KEY) == []

    async def test_closing_one_of_two_tabs_reports_nobody(self, hub: PresenceHub) -> None:
        """The user is still present, so no ``presence_leave`` should fire."""
        first, second = _FakeWS(user_id=USER_A), _FakeWS(user_id=USER_A)
        await hub.join(KEY, first, user_id=USER_A, user_name="Ann")
        await hub.join(KEY, second, user_id=USER_A, user_name="Ann")
        assert await hub.leave(KEY, first) == []
        assert hub.roster(KEY) == [{"user_id": str(USER_A), "user_name": "Ann"}]

    async def test_one_user_leaving_a_shared_room_reports_only_that_user(self, hub: PresenceHub) -> None:
        ws_a, ws_b = _FakeWS(user_id=USER_A), _FakeWS(user_id=USER_B)
        await hub.join(KEY, ws_a, user_id=USER_A, user_name="Ann")
        await hub.join(KEY, ws_b, user_id=USER_B, user_name="Ben")
        assert await hub.leave(KEY, ws_a) == [USER_A]
        assert hub.roster(KEY) == [{"user_id": str(USER_B), "user_name": "Ben"}]

    async def test_leaving_an_unknown_key_is_a_no_op(self, hub: PresenceHub) -> None:
        assert await hub.leave(("boq", uuid.uuid4()), _FakeWS(user_id=USER_A)) == []

    async def test_leaving_twice_does_not_report_the_user_twice(self, hub: PresenceHub) -> None:
        ws = _FakeWS(user_id=USER_A)
        await hub.join(KEY, ws, user_id=USER_A, user_name="Ann")
        assert await hub.leave(KEY, ws) == [USER_A]
        assert await hub.leave(KEY, ws) == []

    async def test_the_last_socket_leaving_reports_every_user_on_the_roster(self, hub: PresenceHub) -> None:
        """Emptying the room announces everyone, not an arbitrary one of them.

        Reachable whenever the roster holds more users than the socket set can
        account for. Returning a single id here left the others painted as
        present in every peer's UI with no event to clear them.
        """
        anchor = _FakeWS(user_id=USER_A)
        await hub.join(KEY, anchor, user_id=USER_A, user_name="Ann")
        await hub.join(KEY, anchor, user_id=USER_B, user_name="Ben")

        assert await hub.leave(KEY, anchor) == [USER_A, USER_B]
        assert hub.roster(KEY) == []

    async def test_leave_depends_on_the_user_id_the_router_stamps_on_the_socket(
        self,
        hub: PresenceHub,
    ) -> None:
        """A cross-file contract with nothing else pinning it.

        ``leave`` works out who remains by reading ``_collab_lock_user_id`` off
        the other sockets. A socket without it counts as nobody, so the user it
        belongs to is evicted from the roster even though the tab is still open
        and still receiving broadcasts. This test states that dependency, so a
        change in the router that drops the attribute fails here rather than
        silently emptying every presence list in production.
        """
        stamped = _FakeWS(user_id=USER_A)
        unstamped = _FakeWS()  # what the router would produce without line ~518
        await hub.join(KEY, stamped, user_id=USER_A, user_name="Ann")
        await hub.join(KEY, unstamped, user_id=USER_B, user_name="Ben")

        # Ann closes her tab. Ben is still connected, but his socket carries no
        # identity, so the hub cannot see him and drops him from the roster.
        left = await hub.leave(KEY, stamped)
        assert hub.subscriber_count(KEY) == 1, "Ben's socket is still subscribed"
        assert hub.roster(KEY) == [], "but the hub no longer knows he is there"
        # Both are reported, so at least the peers' UIs stay consistent with the
        # roster. Ben being dropped at all is the bug this test documents.
        assert left == [USER_A, USER_B]

    def test_the_router_still_stamps_the_attribute(self) -> None:
        """The other half of the contract above, checked at the source."""
        import inspect

        from app.modules.collaboration_locks import router as collab_router

        assert "_collab_lock_user_id" in inspect.getsource(collab_router)

    async def test_every_evicted_user_is_reported_not_just_the_last(self, hub: PresenceHub) -> None:
        """The regression this module was fixed for.

        ``leave`` used to overwrite a single ``left_uid`` as it walked the users
        it could no longer account for, so when several disappeared at once only
        one ``presence_leave`` was broadcast and the rest lingered in every
        peer's UI with nothing to clear them. All of them are returned now, in
        roster order.
        """
        user_c = uuid.uuid4()
        anchor = _FakeWS(user_id=USER_A)
        await hub.join(KEY, anchor, user_id=USER_A, user_name="Ann")
        await hub.join(KEY, _FakeWS(), user_id=USER_B, user_name="Ben")
        await hub.join(KEY, _FakeWS(), user_id=user_c, user_name="Cal")

        left = await hub.leave(KEY, anchor)
        assert hub.roster(KEY) == []
        assert left == [USER_A, USER_B, user_c]

    async def test_the_router_broadcasts_one_event_per_departing_user(self) -> None:
        """``leave`` returning a list is only a fix if the caller iterates it.

        Matched on the loop shape rather than on the loop variable's name, so
        renaming it does not fail the test for a reason the message cannot
        explain. What must not come back is the single-value form, where one
        departure was broadcast and the rest were dropped.
        """
        import inspect
        import re

        from app.modules.collaboration_locks import router as collab_router

        source = inspect.getsource(collab_router)
        assert re.search(r"for \w+ in await presence_hub\.leave\(", source), (
            "the disconnect handler must iterate every id leave() returns"
        )
        assert not re.search(r"\w+ = await presence_hub\.leave\(", source), (
            "binding leave() to a single name is the bug this test pins"
        )


class TestBroadcast:
    async def test_every_subscriber_receives_the_event(self, hub: PresenceHub) -> None:
        ws_a, ws_b = _FakeWS(user_id=USER_A), _FakeWS(user_id=USER_B)
        await hub.join(KEY, ws_a, user_id=USER_A, user_name="Ann")
        await hub.join(KEY, ws_b, user_id=USER_B, user_name="Ben")
        assert await hub.broadcast(KEY, {"type": "lock_acquired"}) == 2
        assert ws_a.sent == ws_b.sent == [{"type": "lock_acquired"}]

    async def test_the_originator_can_be_excluded(self, hub: PresenceHub) -> None:
        ws_a, ws_b = _FakeWS(user_id=USER_A), _FakeWS(user_id=USER_B)
        await hub.join(KEY, ws_a, user_id=USER_A, user_name="Ann")
        await hub.join(KEY, ws_b, user_id=USER_B, user_name="Ben")
        assert await hub.broadcast(KEY, {"type": "lock_acquired"}, exclude=ws_a) == 1
        assert ws_a.sent == []
        assert ws_b.sent == [{"type": "lock_acquired"}]

    async def test_broadcasting_to_an_unknown_key_sends_nothing(self, hub: PresenceHub) -> None:
        assert await hub.broadcast(("boq", uuid.uuid4()), {"type": "x"}) == 0

    async def test_a_dead_socket_is_scrubbed_and_the_rest_still_receive(self, hub: PresenceHub) -> None:
        """A closed tab must not leak, and must not block delivery to others."""
        dead, alive = _FakeWS(user_id=USER_A, fail=True), _FakeWS(user_id=USER_B)
        await hub.join(KEY, dead, user_id=USER_A, user_name="Ann")
        await hub.join(KEY, alive, user_id=USER_B, user_name="Ben")

        assert await hub.broadcast(KEY, {"type": "lock_released"}) == 1
        assert alive.sent == [{"type": "lock_released"}]
        assert hub.subscriber_count(KEY) == 1

    async def test_the_key_is_freed_when_every_socket_is_dead(self, hub: PresenceHub) -> None:
        dead = _FakeWS(user_id=USER_A, fail=True)
        await hub.join(KEY, dead, user_id=USER_A, user_name="Ann")
        assert await hub.broadcast(KEY, {"type": "lock_released"}) == 0
        assert hub.subscriber_count(KEY) == 0

    async def test_concurrent_broadcasts_all_arrive(self, hub: PresenceHub) -> None:
        """The hub keeps a lock per key; overlapping sends must not drop one."""
        ws = _FakeWS(user_id=USER_A)
        await hub.join(KEY, ws, user_id=USER_A, user_name="Ann")
        sent = await asyncio.gather(*(hub.broadcast(KEY, {"n": n}) for n in range(5)))
        assert sent == [1, 1, 1, 1, 1]
        assert sorted(payload["n"] for payload in ws.sent) == [0, 1, 2, 3, 4]


class TestReset:
    async def test_reset_drops_every_subscriber(self, hub: PresenceHub) -> None:
        await hub.join(KEY, _FakeWS(user_id=USER_A), user_id=USER_A, user_name="Ann")
        hub.reset()
        assert hub.subscriber_count(KEY) == 0


# ---------------------------------------------------------------------------
# Sweeper
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    """Records the order of ``execute`` and ``commit`` for the ordering test."""

    def __init__(self, rows: list[Any], *, calls: list[str]) -> None:
        self._rows = rows
        self.calls = calls

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def execute(self, _stmt: object) -> _FakeResult:
        self.calls.append("execute")
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        self.calls.append("commit")


def _expired_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        entity_type="boq",
        entity_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, str]]]:
    from app.core import events as events_mod

    seen: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(
        events_mod.event_bus,
        "publish_detached",
        lambda name, data, source_module=None: seen.append((name, data)),
    )
    return seen


class TestSweepOnce:
    async def test_an_empty_sweep_removes_nothing_and_announces_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        published: list[tuple[str, dict[str, str]]],
    ) -> None:
        monkeypatch.setattr(sweeper_mod, "async_session_factory", lambda: _FakeSession([], calls=[]))
        assert await sweeper_mod._sweep_once() == 0
        assert published == []

    async def test_every_expired_lock_is_announced_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        published: list[tuple[str, dict[str, str]]],
    ) -> None:
        rows = [_expired_row(), _expired_row()]
        monkeypatch.setattr(sweeper_mod, "async_session_factory", lambda: _FakeSession(rows, calls=[]))

        assert await sweeper_mod._sweep_once() == 2
        assert [name for name, _ in published] == [
            sweeper_mod.COLLAB_LOCK_EXPIRED,
            sweeper_mod.COLLAB_LOCK_EXPIRED,
        ]
        # The payload must identify the lock and the entity the UI is showing.
        assert [data["lock_id"] for _, data in published] == [str(row.id) for row in rows]
        assert published[0][1]["entity_type"] == "boq"
        assert published[0][1]["entity_id"] == str(rows[0].entity_id)
        assert published[0][1]["user_id"] == str(rows[0].user_id)

    async def test_the_announcement_happens_after_the_commit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        published: list[tuple[str, dict[str, str]]],
    ) -> None:
        """Otherwise a subscriber could react to a removal that rolled back."""
        calls: list[str] = []
        monkeypatch.setattr(
            sweeper_mod,
            "async_session_factory",
            lambda: _FakeSession([_expired_row()], calls=calls),
        )
        await sweeper_mod._sweep_once()
        assert calls == ["execute", "commit"]
        assert published, "the event fired"

    async def test_a_database_failure_is_swallowed_so_the_loop_survives(
        self,
        monkeypatch: pytest.MonkeyPatch,
        published: list[tuple[str, dict[str, str]]],
    ) -> None:
        """The sweeper runs forever; one bad sweep must not kill it, and it
        must not announce expiries it failed to perform."""

        def _boom() -> _FakeSession:
            raise RuntimeError("connection reset")

        monkeypatch.setattr(sweeper_mod, "async_session_factory", _boom)
        assert await sweeper_mod._sweep_once() == 0
        assert published == []


class TestSweeperLifecycle:
    def test_starting_without_a_running_loop_is_a_no_op(self) -> None:
        """Import-time or sync-context calls must not raise; ``on_startup``
        starts it for real."""
        sweeper_mod.stop_sweeper()
        sweeper_mod.start_sweeper()
        assert sweeper_mod._task is None

    async def test_start_is_idempotent(self) -> None:
        try:
            sweeper_mod.start_sweeper()
            first = sweeper_mod._task
            sweeper_mod.start_sweeper()
            assert sweeper_mod._task is first, "a second call must not spawn a rival sweeper"
            assert first is not None
            assert not first.done()
        finally:
            sweeper_mod.stop_sweeper()

    async def test_stop_cancels_the_task_and_clears_it(self) -> None:
        sweeper_mod.start_sweeper()
        task = sweeper_mod._task
        assert task is not None
        sweeper_mod.stop_sweeper()
        assert sweeper_mod._task is None
        with pytest.raises(asyncio.CancelledError):
            await task

    def test_stopping_when_not_started_is_a_no_op(self) -> None:
        sweeper_mod._task = None
        sweeper_mod.stop_sweeper()
        assert sweeper_mod._task is None
