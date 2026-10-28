"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for app.modules.timeline.mapping.

The mapping module imports only the standard library, but importing it via the
normal dotted path would execute ``app/modules/timeline/__init__.py`` (which
imports the DB-bound router). To keep this test pure and runnable under Python
3.11 without standing up the app, we load ``mapping.py`` directly from its file
path with no package side effects.

Every event name below is one ``app/`` actually publishes. That was not true of
an earlier version of this file, and it is why the module's allowlist could
name nine families that exist nowhere in the codebase while fifteen tests here
passed: the tests only ever asked the mapping about names the mapping itself
had invented, so the two agreed with each other and neither agreed with the
platform. Checking a name against reality is not this file's job - it cannot
see ``app/`` - and is gated in
``tests/modules/timeline/test_timeline_coverage.py``. Using real names here
anyway keeps the two files from drifting apart again.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

_MAPPING_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "timeline" / "mapping.py"
_spec = importlib.util.spec_from_file_location("timeline_mapping_under_test", _MAPPING_PATH)
assert _spec is not None and _spec.loader is not None
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)


# --- is_significant -----------------------------------------------------------


def test_is_significant_true_for_allowlisted_prefixes() -> None:
    assert mapping.is_significant("changeorders.candidate_from_moc") is True
    assert mapping.is_significant("ncr.created") is True
    assert mapping.is_significant("qms.ncr.raised") is True
    assert mapping.is_significant("schedule_advanced.actuals_update") is True
    assert mapping.is_significant("inspection.completed.failed") is True


def test_is_significant_false_for_non_allowlisted() -> None:
    assert mapping.is_significant("erp_chat.message.created") is False
    assert mapping.is_significant("cad.import.completed") is False
    assert mapping.is_significant("documents.document.updated") is False


def test_is_significant_defensive_on_bad_input() -> None:
    assert mapping.is_significant("") is False
    assert mapping.is_significant(None) is False  # type: ignore[arg-type]
    assert mapping.is_significant(123) is False  # type: ignore[arg-type]
    # A bare token without the trailing dot must NOT match the prefix.
    assert mapping.is_significant("ncr") is False


# --- map_event: significance gate ---------------------------------------------


def test_map_event_returns_none_for_insignificant() -> None:
    assert mapping.map_event("erp_chat.message.created", {"id": "x"}) is None
    assert mapping.map_event("cad.import.completed", {}) is None


# --- map_event: module / entity_type / action derivation ----------------------


def test_map_event_two_token_event() -> None:
    pid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    out = mapping.map_event("invoice.approved", {"id": cid, "project_id": pid})
    assert out is not None
    assert out["action"] == "invoice.approved"
    assert out["module"] == "invoice"
    # Two tokens -> entity_type is the single module token.
    assert out["entity_type"] == "invoice"
    assert out["entity_id"] == cid
    assert out["parent_entity_type"] == "project"
    assert out["parent_entity_id"] == pid


def test_map_event_module_id_fallback() -> None:
    out = mapping.map_event("ncr.created", {"ncr_id": "ncr-7", "project_id": "proj-9"})
    assert out is not None
    assert out["module"] == "ncr"
    assert out["entity_type"] == "ncr"
    assert out["action"] == "ncr.created"
    # No "id" key -> falls back to "{module}_id".
    assert out["entity_id"] == "ncr-7"
    assert out["parent_entity_id"] == "proj-9"


def test_map_event_three_token_entity_type() -> None:
    out = mapping.map_event("moc.entry.auto_proposed", {"id": "b1", "project_id": "p1"})
    assert out is not None
    # Three tokens -> entity_type is first.second.
    assert out["entity_type"] == "moc.entry"
    assert out["module"] == "moc"
    assert out["action"] == "moc.entry.auto_proposed"


# --- map_event: entity-id key precedence + fallbacks --------------------------


def test_map_event_id_key_takes_precedence() -> None:
    out = mapping.map_event(
        "ncr.created",
        {"id": "primary", "ncr_id": "secondary", "entity_id": "tertiary", "project_id": "p"},
    )
    assert out is not None
    assert out["entity_id"] == "primary"


def test_map_event_entity_id_fallback() -> None:
    out = mapping.map_event("approval.overdue", {"entity_id": "e-42"})
    assert out is not None
    assert out["entity_id"] == "e-42"
    # No project id present -> no parent rollup.
    assert out["parent_entity_type"] is None
    assert out["parent_entity_id"] is None


def test_map_event_missing_entity_id_is_none() -> None:
    out = mapping.map_event("ncr.created", {"project_id": "p"})
    assert out is not None
    assert out["entity_id"] is None
    assert out["parent_entity_id"] == "p"


# --- map_event: defensiveness -------------------------------------------------


def test_map_event_tolerates_none_data() -> None:
    out = mapping.map_event("ncr.created", None)
    assert out is not None
    assert out["entity_id"] is None
    assert out["parent_entity_id"] is None
    assert out["metadata"] == {}


def test_map_event_tolerates_non_dict_data() -> None:
    out = mapping.map_event("ncr.created", ["not", "a", "dict"])  # type: ignore[arg-type]
    assert out is not None
    assert out["metadata"] == {}
    assert out["entity_id"] is None


def test_map_event_coerces_non_string_ids() -> None:
    out = mapping.map_event("cost.back_charge.recorded", {"id": 12345, "project_id": 678})
    assert out is not None
    assert out["entity_id"] == "12345"
    assert out["parent_entity_id"] == "678"


def test_map_event_ignores_blank_ids() -> None:
    out = mapping.map_event("invoice.paid", {"id": "   ", "project_id": ""})
    assert out is not None
    # Whitespace-only / empty ids are treated as absent.
    assert out["entity_id"] is None
    assert out["parent_entity_id"] is None


def test_map_event_metadata_is_copy_not_alias() -> None:
    data = {"id": "x", "project_id": "p", "extra": 1}
    out = mapping.map_event("qms.punch.closed", data)
    assert out is not None
    assert out["metadata"]["extra"] == 1
    # Mutating the returned metadata must not affect the original payload.
    out["metadata"]["extra"] = 999
    assert data["extra"] == 1


def test_map_event_camelcase_project_id() -> None:
    out = mapping.map_event("variation.flagged", {"id": "v1", "projectId": "p-camel"})
    assert out is not None
    assert out["parent_entity_id"] == "p-camel"
    assert out["parent_entity_type"] == "project"


def test_allowlist_prefixes_all_end_with_dot() -> None:
    # Guard the contract: every prefix is dot-terminated so bare tokens never match.
    assert all(p.endswith(".") for p in mapping.ALLOWLIST_PREFIXES)
    assert len(mapping.ALLOWLIST_PREFIXES) == len(set(mapping.ALLOWLIST_PREFIXES))


def test_exact_allowlist_entries_are_whole_dotted_names() -> None:
    # A bare token or a trailing dot here would silently behave like a prefix.
    assert all("." in n and not n.endswith(".") for n in mapping.ALLOWLIST_EVENTS)


def test_no_exact_entry_duplicates_a_prefix() -> None:
    # An entry already matched by a prefix changes nothing and reads as a
    # deliberate inclusion - the same shape as the dead prefixes this module
    # shipped with.
    assert not [n for n in mapping.ALLOWLIST_EVENTS if n.startswith(mapping.ALLOWLIST_PREFIXES)]
