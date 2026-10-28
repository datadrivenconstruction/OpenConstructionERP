# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Entity-id and actor extraction, checked against real publisher payloads.

The payload key lists here are read out of ``app/`` with :mod:`ast` rather than
typed into the test. That is not tidiness: an earlier draft of this check typed
the keys for ``correspondence.outbound.requested`` from memory, invented a
``project_id`` it does not send, and reported the event as routable when it is
not. A payload shape a test imagines is a payload shape nothing publishes.
"""

from __future__ import annotations

import ast
import importlib.util
import uuid
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[3]
_APP = _BACKEND / "app"
_MAPPING_PATH = _APP / "modules" / "timeline" / "mapping.py"

_spec = importlib.util.spec_from_file_location("timeline_mapping_extraction", _MAPPING_PATH)
assert _spec is not None and _spec.loader is not None
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)

_PUBLISH_FUNCS = {"publish", "publish_detached"}


def _literal_payload_keys() -> dict[str, list[str]]:
    """Event name -> payload keys, for literal-dict publish sites in app/."""
    out: dict[str, list[str]] = {}
    for path in sorted(_APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in _PUBLISH_FUNCS:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            payload = node.args[1] if len(node.args) > 1 else None
            for kw in node.keywords:
                if kw.arg in ("data", "payload"):
                    payload = kw.value
            if not isinstance(payload, ast.Dict):
                continue
            out.setdefault(first.value, []).extend(k.value for k in payload.keys if isinstance(k, ast.Constant))
    return out


@pytest.fixture(scope="module")
def payload_keys() -> dict[str, list[str]]:
    return _literal_payload_keys()


# Captured events that legitimately name no single record: each is an
# aggregate about the project itself, so it rolls up to the project feed and
# has nothing narrower to link to. Listed by name rather than waved through by
# a loosened rule, so that a *new* event failing extraction is still a failure.
PROJECT_LEVEL_AGGREGATES: frozenset[str] = frozenset(
    {
        "qms.calibration.expiring",  # a count over calibration_ids, not one record
        "resources.portfolio.overload_detected",  # portfolio-wide rollup
        "safety.threshold_alert_triggered",  # project LTIFR/TRIR against baseline
    }
)


def test_every_captured_event_resolves_an_entity_id(payload_keys) -> None:
    """A timeline row that names no record cannot be opened by a reader.

    Looking only for ``id`` / ``{module}_id`` / ``entity_id`` left six of the
    fourteen captured publish sites with no entity id at all, because
    publishers name the key after the record rather than after the event:
    ``cost.back_charge.recorded`` sends ``back_charge_id``,
    ``moc.candidate_from_ncr`` sends ``ncr_id``.

    The assertion is an equality against the known aggregates rather than a
    subset check, so this also fails if one of them starts resolving an entity
    id - that would mean the last-resort scan had begun picking up a plural or
    a threshold value and calling it a record.
    """
    missing = {
        name
        for name, keys in payload_keys.items()
        if mapping.is_significant(name) and mapping.map_event(name, {k: f"v-{k}" for k in keys})["entity_id"] is None
    }
    assert missing == PROJECT_LEVEL_AGGREGATES, (
        "captured events resolving no entity id changed.\n"
        f"  unexpectedly missing an id: {sorted(missing - PROJECT_LEVEL_AGGREGATES)}\n"
        f"  no longer missing one:      {sorted(PROJECT_LEVEL_AGGREGATES - missing)}"
    )


def test_every_captured_event_is_routable_after_mapping(payload_keys) -> None:
    """The mapped row must satisfy is_routable, which is what the bridge checks."""
    unroutable = [
        name
        for name, keys in sorted(payload_keys.items())
        if mapping.is_significant(name)
        and not mapping.is_routable(mapping.map_event(name, {k: f"v-{k}" for k in keys}))
    ]
    assert not unroutable, f"captured events that map to an unreachable row: {unroutable}"


@pytest.mark.parametrize(
    ("event", "keys", "expected"),
    [
        # The four shapes the {module}_id-only chain used to miss.
        ("cost.back_charge.recorded", ["project_id", "back_charge_id"], "v-back_charge_id"),
        ("moc.entry.auto_proposed", ["project_id", "entry_id"], "v-entry_id"),
        ("moc.candidate_from_ncr", ["source_event", "ncr_id", "project_id"], "v-ncr_id"),
        ("variation.flagged", ["project_id", "source_type", "source_id"], "v-source_id"),
        # And the shapes that already worked, so a regression is visible.
        ("ncr.created", ["project_id", "ncr_id"], "v-ncr_id"),
        ("approval.overdue", ["id", "project_id"], "v-id"),
    ],
)
def test_entity_id_key_resolution(event, keys, expected) -> None:
    row = mapping.map_event(event, {k: f"v-{k}" for k in keys})
    assert row is not None
    assert row["entity_id"] == expected


def test_id_key_still_wins_over_every_fallback() -> None:
    """Precedence must not have been reordered by the new fallbacks."""
    row = mapping.map_event(
        "ncr.created",
        {"id": "primary", "ncr_id": "secondary", "entity_id": "tertiary", "project_id": "p"},
    )
    assert row["entity_id"] == "primary"


def test_project_and_actor_keys_are_never_taken_as_the_entity() -> None:
    """The last-resort *_id scan must skip references that are not the subject."""
    row = mapping.map_event(
        "safety.incident.created",
        {"project_id": "p-1", "tenant_id": "t-1", "user_id": "u-1", "owner_id": "o-1"},
    )
    assert row["entity_id"] is None
    assert row["parent_entity_id"] == "p-1"


def test_actor_is_taken_from_the_payload_when_it_is_a_uuid() -> None:
    actor = uuid.uuid4()
    row = mapping.map_event("ncr.created", {"project_id": "p", "created_by": str(actor)})
    assert row["actor_id"] == actor


def test_actor_that_is_not_a_uuid_is_dropped_rather_than_written() -> None:
    """A name or an email cannot go in the GUID actor column.

    Passing it through would fail the insert, and the bridge swallows failures,
    so the whole row would disappear - an enrichment turning into data loss.
    """
    row = mapping.map_event("ncr.created", {"project_id": "p", "created_by": "Alex Mason"})
    assert row["actor_id"] is None
    # The value is still on the row, so the validation rule can report the loss.
    assert row["metadata"]["created_by"] == "Alex Mason"


def test_unroutable_payload_is_reported_as_such() -> None:
    """The real correspondence payload, verbatim: no project id anywhere."""
    row = mapping.map_event(
        "correspondence.outbound.requested",
        {
            "template": "INSTALMENT_DEMAND",
            "instalment_id": "i-1",
            "schedule_id": "s-1",
            "amount_outstanding": "100",
            "due_date": "2026-01-01",
            "milestone_label": "M1",
        },
    )
    # Not in the allowlist any more, precisely because of this.
    assert row is None
