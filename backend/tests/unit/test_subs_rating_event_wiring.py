# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure-logic tests for the subcontractor rating event wiring (TOP-30 #20).

These cover the parts of ``subcontractors/events.py`` that do not need a
database:

* ``register_subcontractor_rating_subscribers`` wires exactly the three
  rating-driving events (``ncr.created`` / ``safety.incident.created`` /
  ``schedule.activity.slipped``) onto the global :data:`event_bus`, and is
  idempotent (re-registering does not duplicate handlers). This is the
  "event subscriber not wired" risk-row test from the design doc - if the
  subscriber list is ever trimmed or a name typo creeps in, this fails.
* ``_resolve_sub_id`` extracts a subcontractor id from a variety of payload
  shapes (top-level ``subcontractor_id`` / ``sub_id``, nested ``metadata``,
  raw UUID, string UUID) and returns ``None`` on anything unparseable -
  guarding the operator-precedence bug the resolver's docstring calls out.

No session / DB is touched, so these run fast and never hit an event loop
fixture.
"""

from __future__ import annotations

import uuid

from app.core.events import Event, event_bus
from app.modules.subcontractors.events import (
    _SUBSCRIPTIONS,
    _resolve_sub_id,
    register_subcontractor_rating_subscribers,
)

_RATING_EVENTS = (
    "ncr.created",
    "safety.incident.created",
    "schedule.activity.slipped",
)


# ── subscriber wiring ──────────────────────────────────────────────────────


def test_rating_subscribers_registered_for_all_three_events() -> None:
    """Every rating-driving event has at least one subscriber bound."""
    register_subcontractor_rating_subscribers()
    handlers = event_bus.list_handlers()
    for event_name in _RATING_EVENTS:
        assert event_name in handlers, f"{event_name} has no subscriber"
        # The bound handler is one of our module's ``_on_*`` coroutines.
        bound = handlers[event_name]
        assert any("subcontractors.events" in name or "_on_" in name for name in bound), (
            f"{event_name} bound to unexpected handler(s): {bound}"
        )


def _own_handler_counts() -> dict[str, int]:
    """How many copies of *our* handler each rating event carries.

    Counted by identity against ``_SUBSCRIPTIONS`` rather than by taking the
    length of the handler list. The bus is a process-global singleton and these
    are ordinary application events: ``ncr.created`` also carries the core
    notification handler once the application lifespan has run, and any module
    loaded later may add its own. A total is therefore a claim about the whole
    process, which no single test can own - run inside the full suite it read 8
    where it expected 1, and run alone it read 1, which is how a green file and
    a red suite disagreed about the same code.

    What this module *can* own is its own contribution, and that is the number
    the duplicate-subscription bug would change.
    """
    bound = {ev: event_bus._handlers.get(ev, []) for ev in _RATING_EVENTS}
    return {
        event_name: sum(1 for bound_handler in bound[event_name] if bound_handler is handler)
        for event_name, handler in _SUBSCRIPTIONS
        if event_name in _RATING_EVENTS
    }


def test_rating_subscribers_registration_is_idempotent() -> None:
    """A second registration pass does not double-bind the handlers.

    The module registers on import; calling the registrar again (as the
    module loader might on a reload) must not stack duplicate handlers - the
    registrar goes through ``subscribe_once``, which dedupes by handler.
    """
    register_subcontractor_rating_subscribers()
    before = _own_handler_counts()
    register_subcontractor_rating_subscribers()
    register_subcontractor_rating_subscribers()
    after = _own_handler_counts()
    assert before == after
    # Exactly one copy of our handler each - a stacked duplicate would fire the
    # rating bump twice per event (double-counting NCR / HSE / slips).
    assert set(after) == set(_RATING_EVENTS)
    for ev in _RATING_EVENTS:
        assert after[ev] == 1, f"{ev} carries {after[ev]} copies of our handler, expected 1"


# ── _resolve_sub_id ────────────────────────────────────────────────────────


def test_resolve_sub_id_top_level_string() -> None:
    sid = uuid.uuid4()
    assert _resolve_sub_id({"subcontractor_id": str(sid)}) == sid


def test_resolve_sub_id_top_level_uuid_object() -> None:
    sid = uuid.uuid4()
    assert _resolve_sub_id({"subcontractor_id": sid}) == sid


def test_resolve_sub_id_sub_id_alias() -> None:
    sid = uuid.uuid4()
    assert _resolve_sub_id({"sub_id": str(sid)}) == sid


def test_resolve_sub_id_nested_metadata() -> None:
    """The nested-metadata path must work even when no top-level key exists.

    This is the operator-precedence regression the resolver guards: a payload
    carrying the id only under ``metadata`` previously resolved to ``None``.
    """
    sid = uuid.uuid4()
    assert _resolve_sub_id({"metadata": {"subcontractor_id": str(sid)}}) == sid


def test_resolve_sub_id_missing_returns_none() -> None:
    assert _resolve_sub_id({"unrelated": 1}) is None


def test_resolve_sub_id_garbage_value_returns_none() -> None:
    assert _resolve_sub_id({"subcontractor_id": "not-a-uuid"}) is None


def test_resolve_sub_id_metadata_not_a_dict_returns_none() -> None:
    assert _resolve_sub_id({"metadata": "oops"}) is None


def test_resolve_sub_id_from_event_payload() -> None:
    """An Event whose ``data`` carries the id resolves the same way."""
    sid = uuid.uuid4()
    event = Event(name="ncr.created", data={"subcontractor_id": str(sid)})
    assert _resolve_sub_id(event.data) == sid
