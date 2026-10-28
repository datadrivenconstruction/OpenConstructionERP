"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Wiring tests for the RFI / submittals / correspondence semantic assistant.

Item 16 plugs three existing project-document modules into the shared
semantic-search + chat-tool pipeline.  These tests assert the registry,
alias, event-subscription and chat-tool wiring is in place without
booting the database or the embedding model.
"""

from __future__ import annotations

import uuid

import pytest

from app.core import events as events_module
from app.core.events import event_bus
from app.core.vector_index import (
    ALL_COLLECTIONS,
    COLLECTION_CORRESPONDENCE,
    COLLECTION_LABELS,
    COLLECTION_RFI,
    COLLECTION_SUBMITTALS,
)

# -- Registry --------------------------------------------------------------


def test_collection_constants_are_distinct_and_namespaced() -> None:
    cols = {COLLECTION_RFI, COLLECTION_SUBMITTALS, COLLECTION_CORRESPONDENCE}
    assert len(cols) == 3
    for col in cols:
        assert col.startswith("oe_")


def test_collections_registered_in_all_collections() -> None:
    for col in (COLLECTION_RFI, COLLECTION_SUBMITTALS, COLLECTION_CORRESPONDENCE):
        assert col in ALL_COLLECTIONS


def test_collections_have_human_labels() -> None:
    assert COLLECTION_LABELS[COLLECTION_RFI] == "RFI"
    assert COLLECTION_LABELS[COLLECTION_SUBMITTALS] == "Submittals"
    assert COLLECTION_LABELS[COLLECTION_CORRESPONDENCE] == "Correspondence"


# -- Short-name aliases ----------------------------------------------------


def test_short_name_aliases_resolve_both_forms() -> None:
    from app.modules.search.service import _normalize_types

    # Friendly aliases.
    assert _normalize_types(["rfi"]) == [COLLECTION_RFI]
    assert _normalize_types(["submittals"]) == [COLLECTION_SUBMITTALS]
    assert _normalize_types(["correspondence"]) == [COLLECTION_CORRESPONDENCE]
    # Doubled short names emitted by /search/types/ (removeprefix("oe_")).
    assert _normalize_types(["rfi_rfis"]) == [COLLECTION_RFI]
    assert _normalize_types(["submittals_submittals"]) == [COLLECTION_SUBMITTALS]
    assert _normalize_types(["correspondence_correspondence"]) == [COLLECTION_CORRESPONDENCE]
    # Canonical names pass through.
    assert _normalize_types([COLLECTION_RFI]) == [COLLECTION_RFI]


def test_types_endpoint_short_names_round_trip_through_aliases() -> None:
    """The wire ``short`` value from /search/types/ must resolve back."""
    from app.modules.search.service import _normalize_types

    for col in (COLLECTION_RFI, COLLECTION_SUBMITTALS, COLLECTION_CORRESPONDENCE):
        short = col.removeprefix("oe_")
        assert _normalize_types([short]) == [col]


# -- Chat tools ------------------------------------------------------------


def test_chat_tools_registered() -> None:
    from app.modules.erp_chat.tools import (
        TOOL_HANDLER_MAP,
        TOOL_PERMISSIONS,
    )

    for name in ("search_rfis", "search_submittals", "search_correspondence"):
        assert name in TOOL_HANDLER_MAP
        assert TOOL_PERMISSIONS[name] == "read"


def test_chat_tool_definitions_present() -> None:
    from app.modules.erp_chat.tools import TOOL_DEFINITIONS

    names = {d["name"] for d in TOOL_DEFINITIONS}
    assert {"search_rfis", "search_submittals", "search_correspondence"} <= names


# -- Event subscriptions ---------------------------------------------------


def test_event_handlers_subscribed() -> None:
    # Importing the events modules registers the subscribers at import time
    # (mirrors what the module loader does at startup).
    import app.modules.correspondence.events  # noqa: F401
    import app.modules.rfi.events  # noqa: F401
    import app.modules.submittals.events  # noqa: F401

    handlers = event_bus.list_handlers()
    for event_name in (
        "rfi.created",
        "rfi.updated",
        "rfi.deleted",
        "submittal.created",
        "submittal.updated",
        "submittal.deleted",
        "correspondence.created",
        "correspondence.updated",
        "correspondence.deleted",
    ):
        assert handlers.get(event_name), f"no handler subscribed for {event_name}"


# -- Event handler behaviour (delete path, no DB needed) -------------------


@pytest.mark.asyncio
async def test_rfi_delete_handler_calls_vector_delete(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import app.modules.rfi.events as rfi_events

    captured: dict[str, str] = {}

    async def _fake_delete(adapter, row_id):  # type: ignore[no-untyped-def]
        captured["collection"] = adapter.collection_name
        captured["row_id"] = str(row_id)
        return True

    monkeypatch.setattr(rfi_events, "vector_delete_one", _fake_delete)

    rid = str(uuid.uuid4())
    event = events_module.Event(name="rfi.deleted", data={"rfi_id": rid})
    await rfi_events._on_rfi_deleted(event)

    assert captured["collection"] == COLLECTION_RFI
    assert captured["row_id"] == rid


@pytest.mark.asyncio
async def test_delete_handler_ignores_missing_id(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import app.modules.submittals.events as sub_events

    called = {"n": 0}

    async def _fake_delete(adapter, row_id):  # type: ignore[no-untyped-def]
        called["n"] += 1
        return True

    monkeypatch.setattr(sub_events, "vector_delete_one", _fake_delete)

    event = events_module.Event(name="submittal.deleted", data={})
    await sub_events._on_submittal_deleted(event)
    assert called["n"] == 0
