"""Unit tests for BOQ event wiring + vector-indexing error logging (v2.4.0).

Two audit findings are exercised here:

1. The wildcard activity-log handler is registered at import time. (It
   used to be skipped on SQLite to avoid ``MissingGreenlet``; the app is
   PostgreSQL-only now, so the handler is always registered.)

2. Vector-indexing failures used to log at DEBUG, meaning a broken
   embedding service silently stopped indexing in production.  They
   now route through a :class:`_RateLimitedLogger` at WARNING — one
   line per ``(op, error-type)`` per 60 s so an outage produces
   signal without flooding.

Pattern mirrors :mod:`tests.unit.test_cache_logging`.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import cache as cache_mod
from app.core.events import Event, event_bus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot_bus() -> tuple[dict[str, list], list]:
    """Copy both event-bus registries so they can be put back verbatim."""
    return (
        {name: list(handlers) for name, handlers in event_bus._handlers.items()},
        list(event_bus._wildcard_handlers),
    )


def _restore_bus(snapshot: tuple[dict[str, list], list]) -> None:
    """Put the event bus back exactly as :func:`_snapshot_bus` found it."""
    named, wildcard = snapshot
    event_bus._handlers.clear()
    for name, handlers in named.items():
        event_bus._handlers[name] = list(handlers)
    event_bus._wildcard_handlers[:] = wildcard


@pytest.fixture(autouse=True)
def _restore_event_bus():
    """Undo, per test, everything the reload helper below does to the bus.

    ``_reload_boq_events`` clears the global bus and re-runs the BOQ module's
    ``_register_handlers()``. Both halves leak: the clear drops every *other*
    module's subscriptions for the rest of the process, and the re-registration
    leaves ``_on_position_created`` subscribed to ``boq.position.created`` with
    nobody to take it off again. A later BOQ test that wrote a position then
    published into that leaked subscriber, which opens its own asyncpg session -
    on Windows the whole file after it died in ``selectors.py`` with WinError
    10038, deterministically, and passed the moment the two files were ordered
    the other way round.

    A test that re-registers handlers on a process-global bus owns putting the
    bus back. Snapshot both registries, restore them verbatim.
    """
    snapshot = _snapshot_bus()
    try:
        yield
    finally:
        _restore_bus(snapshot)


def _reload_boq_events(database_url: str):
    """Re-import :mod:`app.modules.boq.events` under a monkeypatched
    ``database_url`` so the module-level ``_register_handlers()`` call
    observes the dialect we want.

    Clears the global event bus first so we have a clean slate — tests
    that follow rely on the handler list being deterministic.
    """
    event_bus.clear()
    # Also reset the process-wide rate limiter so warnings don't get
    # collapsed across tests.  Mirrors test_cache_logging's
    # ``fresh_cache`` fixture.
    import app.modules.boq.events as boq_events_mod  # noqa: I001

    stub_settings = MagicMock()
    stub_settings.database_url = database_url
    with patch("app.config.get_settings", return_value=stub_settings):
        importlib.reload(boq_events_mod)
    boq_events_mod._vector_warn = cache_mod._RateLimitedLogger(window_seconds=60.0)
    return boq_events_mod


# ---------------------------------------------------------------------------
# Activity-log wildcard handler registration
# ---------------------------------------------------------------------------


class TestWildcardHandlerRegistration:
    def test_wildcard_handler_is_registered(self):
        """The activity-log wildcard handler is always registered.

        The app is PostgreSQL-only, so the old SQLite skip path is gone and the
        handler is registered unconditionally at import time, alongside the
        per-event vector handlers.
        """
        mod = _reload_boq_events("postgresql+asyncpg://oe:oe@localhost:5432/openestimate")

        assert mod._log_boq_activity in event_bus._wildcard_handlers
        assert mod._on_position_created in event_bus._handlers.get("boq.position.created", [])
        assert mod._on_position_updated in event_bus._handlers.get("boq.position.updated", [])
        assert mod._on_position_deleted in event_bus._handlers.get("boq.position.deleted", [])


# ---------------------------------------------------------------------------
# Vector-indexing failure path
# ---------------------------------------------------------------------------


class TestVectorIndexFailureLogging:
    @pytest.mark.asyncio
    async def test_single_failure_logs_at_warning(self, caplog):
        mod = _reload_boq_events("postgresql+asyncpg://oe:oe@localhost:5432/openestimate")

        # Make the inner index call blow up — the key thing we want to
        # assert is that the failure surfaces at WARNING, not DEBUG.
        with (
            caplog.at_level(logging.WARNING, logger="app.core.cache"),
            patch.object(
                mod,
                "vector_index_one",
                AsyncMock(side_effect=ConnectionError("embeddings-down")),
            ),
            patch.object(mod, "async_session_factory") as session_factory,
        ):
            fake_row = MagicMock(boq=MagicMock(project_id=uuid.uuid4()))
            fake_session = AsyncMock()
            fake_session.execute = AsyncMock(
                return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
            )
            session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            pid = uuid.uuid4()
            evt = Event(name="boq.position.created", data={"position_id": str(pid)})
            await mod._on_position_created(evt)

        records = [
            rec
            for rec in caplog.records
            if "boq.vector.index" in rec.getMessage() and "ConnectionError" in rec.getMessage()
        ]
        assert records, "vector-index failure was not logged"
        assert records[0].levelno == logging.WARNING

    @pytest.mark.asyncio
    async def test_duplicate_failure_within_window_is_suppressed(self, caplog):
        """Second identical failure within 60 s must not produce a log line."""
        mod = _reload_boq_events("postgresql+asyncpg://oe:oe@localhost:5432/openestimate")

        # Install a fresh rate limiter scoped to this test, with 60s
        # window — we'll call the handler twice and expect exactly one
        # emission.
        mod._vector_warn = cache_mod._RateLimitedLogger(window_seconds=60.0)

        with (
            caplog.at_level(logging.WARNING, logger="app.core.cache"),
            patch.object(
                mod,
                "vector_index_one",
                AsyncMock(side_effect=ConnectionError("embeddings-down")),
            ),
            patch.object(mod, "async_session_factory") as session_factory,
        ):
            fake_row = MagicMock(boq=MagicMock(project_id=uuid.uuid4()))
            fake_session = AsyncMock()
            fake_session.execute = AsyncMock(
                return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
            )
            session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            for _ in range(5):
                evt = Event(
                    name="boq.position.created",
                    data={"position_id": str(uuid.uuid4())},
                )
                await mod._on_position_created(evt)

        records = [rec for rec in caplog.records if "boq.vector.index" in rec.getMessage()]
        assert len(records) == 1, f"expected exactly one collapsed WARNING, got {len(records)}"

    @pytest.mark.asyncio
    async def test_delete_failure_logs_distinct_operation(self, caplog):
        """Index and delete are separate buckets in the limiter."""
        mod = _reload_boq_events("postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
        mod._vector_warn = cache_mod._RateLimitedLogger(window_seconds=60.0)

        with (
            caplog.at_level(logging.WARNING, logger="app.core.cache"),
            patch.object(
                mod,
                "vector_delete_one",
                AsyncMock(side_effect=RuntimeError("delete-boom")),
            ),
        ):
            evt = Event(
                name="boq.position.deleted",
                data={"position_id": str(uuid.uuid4())},
            )
            await mod._on_position_deleted(evt)

        records = [rec for rec in caplog.records if "boq.vector.delete" in rec.getMessage()]
        assert records
        assert records[0].levelno == logging.WARNING


# ---------------------------------------------------------------------------
# Activity-log scope columns are foreign keys
# ---------------------------------------------------------------------------


class _FakeSession:
    """Records what was added and lets a test decide what commit does."""

    def __init__(self, on_commit=None):
        self.added: list = []
        self._on_commit = on_commit

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        if self._on_commit is not None:
            raise self._on_commit


class _SessionCtx:
    def __init__(self, session: _FakeSession):
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *exc) -> bool:
        return False


class _FactoryStub:
    """Stands in for ``async_session_factory``, one session per call.

    ``commit_effects`` are raised in turn, one per session opened, so a test
    can make the first write fail and the retry succeed.
    """

    def __init__(self, *commit_effects):
        self.sessions: list[_FakeSession] = []
        self._effects = list(commit_effects)

    def __call__(self) -> _SessionCtx:
        effect = self._effects.pop(0) if self._effects else None
        session = _FakeSession(effect)
        self.sessions.append(session)
        return _SessionCtx(session)

    @property
    def rows(self) -> list:
        return [row for session in self.sessions for row in session.added]


def _integrity_error() -> IntegrityError:
    return IntegrityError("INSERT INTO oe_boq_activity_log ...", {}, Exception("foreign key violation"))


class TestActivityLogScopeColumns:
    """``project_id`` and ``boq_id`` are foreign keys, and the trail is the
    thing that must survive - not the scope filter it would be nice to have.
    """

    @pytest.mark.asyncio
    async def test_deleting_a_boq_is_recorded_without_the_scope_that_is_gone(self):
        """The one event whose parent row is provably absent.

        ``delete_boq`` removes the row and publishes afterwards, and the
        handler commits in a session of its own, so PostgreSQL rejects the
        entry outright if it carries the id in the FK column - which loses the
        deletion from the audit trail entirely. The id belongs in
        ``target_id``, which has no foreign key on it.
        """
        import app.modules.boq.events as mod  # noqa: I001

        boq_id = uuid.uuid4()
        project_id = uuid.uuid4()
        factory = _FactoryStub()
        with patch.object(mod, "async_session_factory", factory):
            await mod._log_boq_activity(
                Event(
                    name="boq.boq.deleted",
                    data={"boq_id": str(boq_id), "project_id": str(project_id)},
                    source_module="oe_boq",
                )
            )

        assert len(factory.rows) == 1, "the deletion has to reach the trail"
        row = factory.rows[0]
        assert row.boq_id is None
        assert row.target_id == boq_id, "the id survives where no foreign key can reject it"
        assert row.project_id == project_id, "the project is still there and still scopes the entry"
        assert row.action == "boq.deleted"

    @pytest.mark.asyncio
    async def test_a_living_boq_keeps_its_scope(self):
        """The guard is about the deletion, not about the column.

        Every other event names a BOQ that exists, and the per-BOQ activity
        feed reads that column, so nulling it wholesale would empty the feed.
        """
        import app.modules.boq.events as mod  # noqa: I001

        boq_id = uuid.uuid4()
        factory = _FactoryStub()
        with patch.object(mod, "async_session_factory", factory):
            await mod._log_boq_activity(
                Event(
                    name="boq.position.created",
                    data={"boq_id": str(boq_id), "position_id": str(uuid.uuid4())},
                    source_module="oe_boq",
                )
            )

        assert factory.rows[0].boq_id == boq_id

    @pytest.mark.asyncio
    async def test_a_missing_scope_row_costs_the_scope_not_the_entry(self, caplog):
        """A row deleted while the event was in flight is a race, not a rule.

        There is no ordering to fix it with, so the entry is written again
        without the scope. An audit trail that drops entries when a parent
        disappears is worse than one that keeps them unscoped.
        """
        import app.modules.boq.events as mod  # noqa: I001

        boq_id = uuid.uuid4()
        project_id = uuid.uuid4()
        factory = _FactoryStub(_integrity_error())
        with caplog.at_level(logging.WARNING), patch.object(mod, "async_session_factory", factory):
            await mod._log_boq_activity(
                Event(
                    name="boq.position.updated",
                    data={"boq_id": str(boq_id), "project_id": str(project_id)},
                    source_module="oe_boq",
                )
            )

        assert len(factory.sessions) == 2, "the failed write is retried once"
        retried = factory.sessions[1].added[0]
        assert retried.boq_id is None
        assert retried.project_id is None
        assert retried.action == "position.updated"
        assert any("no longer exists" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_a_propagation_is_logged_in_every_bill_it_repriced(self):
        """One fan-out event, one entry per bill whose lines it changed.

        The event's ``boq_id`` is the bill of the edited line. Logged once, a
        second bill whose lines were re-priced from the first would show nothing
        in its own feed, which filters by ``boq_id``. Each entry names that
        bill's lines and counts them.
        """
        import app.modules.boq.events as mod  # noqa: I001

        editor_boq, other_boq, project_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        edited, near, far_1, far_2 = (str(uuid.uuid4()) for _ in range(4))
        factory = _FactoryStub()
        with patch.object(mod, "async_session_factory", factory):
            await mod._log_boq_activity(
                Event(
                    name="boq.positions.resource_propagated",
                    data={
                        "project_id": str(project_id),
                        "boq_id": str(editor_boq),
                        "propagated_from": edited,
                        "count": 3,
                        "changes": {
                            "resource_code_propagation": ["SHR-100"],
                            "position_ids": [near, far_1, far_2],
                            "boq_ids": sorted([str(editor_boq), str(other_boq)]),
                            "positions_by_boq": {str(editor_boq): [near], str(other_boq): [far_1, far_2]},
                        },
                    },
                    source_module="oe_boq",
                )
            )

        by_boq = {row.boq_id: row for row in factory.rows}
        assert set(by_boq) == {editor_boq, other_boq}
        assert by_boq[other_boq].changes["position_ids"] == [far_1, far_2]
        assert by_boq[other_boq].description == "Propagated a resource definition to 2 position(s)"
        assert by_boq[editor_boq].changes["position_ids"] == [near]
        assert by_boq[editor_boq].changes["propagated_from"] == edited
        assert all(row.project_id == project_id for row in factory.rows)
        assert all(row.action == "positions.resource_propagated" for row in factory.rows)


# ---------------------------------------------------------------------------
# Cleanup — restore module to its natural (settings-driven) state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _reset_after_module():
    """Leave :mod:`app.modules.boq.events` itself loaded under the real settings.

    The per-test fixture above restores the bus, so this only has to undo the
    monkeypatched reload of the module object. It reloads inside its own
    snapshot/restore because that reload re-runs ``_register_handlers()`` too:
    without the guard, module teardown would put back exactly the leak the
    per-test fixture spent the file removing.
    """
    yield
    snapshot = _snapshot_bus()
    try:
        import app.modules.boq.events as boq_events_mod  # noqa: I001

        importlib.reload(boq_events_mod)
    finally:
        _restore_bus(snapshot)


class TestActivityText:
    """No event name reaches the feed as text, mapped or not."""

    def test_an_event_without_a_sentence_is_humanized(self):
        from app.modules.boq.events import _build_description

        assert _build_description("boq.some_new.thing_happened", {}) == "Some new thing happened"

    def test_every_published_boq_event_has_a_sentence(self):
        from app.modules.boq.events import _EVENT_DESCRIPTIONS

        for name in (
            "boq.positions.bulk_created",
            "boq.quantity_link.created",
            "boq.quantity_link.applied",
        ):
            assert name in _EVENT_DESCRIPTIONS, name

    @pytest.mark.asyncio
    async def test_a_read_only_event_writes_no_row(self):
        events_mod = importlib.import_module("app.modules.boq.events")
        with patch.object(events_mod, "async_session_factory") as factory:
            await events_mod._log_boq_activity(
                Event(name="boq.cost_breakdown.computed", data={"boq_id": str(uuid.uuid4())})
            )
        factory.assert_not_called()
