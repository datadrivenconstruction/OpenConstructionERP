# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the schedule interchange cleaner (T1.1).

Stdlib + the pure modules only, so they run on the local Python 3.11 runner.
Each test drives one repair (or the advisory metrics) through
``clean_document`` and asserts both the cleaned document and the reported
action(s). Also pins idempotency and input-immutability.
"""

from __future__ import annotations

from app.modules.schedule.schedule_clean import clean_document
from app.modules.schedule.schedule_interchange import (
    FORMAT,
    FORMAT_VERSION,
    canonicalize,
    parse_document,
)


def _doc(activities: list[dict], relationships: list[dict] | None = None):
    raw = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "schedule": {"name": "S"},
        "activities": activities,
        "relationships": relationships or [],
    }
    return parse_document(raw)


def _codes(result) -> set[str]:
    return {a.code for a in result.actions}


def test_drop_dangling_relationship() -> None:
    doc = _doc(
        [{"ref": "A1"}],
        [{"predecessor_ref": "A1", "successor_ref": "ghost", "relationship_type": "FS", "lag_days": 0}],
    )
    res = clean_document(doc)
    assert res.document.relationships == []
    assert "drop_dangling_relationship" in _codes(res)
    assert res.stats["relationships_dropped_dangling"] == 1


def test_drop_self_link() -> None:
    doc = _doc(
        [{"ref": "A1"}],
        [{"predecessor_ref": "A1", "successor_ref": "A1", "relationship_type": "FS", "lag_days": 0}],
    )
    res = clean_document(doc)
    assert res.document.relationships == []
    assert "drop_self_relationship" in _codes(res)


def test_dedupe_duplicate_relationship() -> None:
    rel = {"predecessor_ref": "A1", "successor_ref": "A2", "relationship_type": "FS", "lag_days": 0}
    doc = _doc([{"ref": "A1"}, {"ref": "A2"}], [dict(rel), dict(rel)])
    res = clean_document(doc)
    assert len(res.document.relationships) == 1
    assert res.stats["relationships_deduped"] == 1


def test_coerce_invalid_relationship_type() -> None:
    doc = _doc(
        [{"ref": "A1"}, {"ref": "A2"}],
        [{"predecessor_ref": "A1", "successor_ref": "A2", "relationship_type": "ZZ", "lag_days": 0}],
    )
    res = clean_document(doc)
    assert res.document.relationships[0]["relationship_type"] == "FS"
    assert "coerce_relationship_type" in _codes(res)


def test_lowercase_relationship_type_is_upcased_not_counted() -> None:
    doc = _doc(
        [{"ref": "A1"}, {"ref": "A2"}],
        [{"predecessor_ref": "A1", "successor_ref": "A2", "relationship_type": "ss", "lag_days": 0}],
    )
    res = clean_document(doc)
    assert res.document.relationships[0]["relationship_type"] == "SS"
    assert res.stats["relationship_types_coerced"] == 0


def test_clear_dangling_parent() -> None:
    doc = _doc([{"ref": "A1", "parent_ref": "ghost"}])
    res = clean_document(doc)
    assert res.document.activities[0]["parent_ref"] is None
    assert "clear_dangling_parent" in _codes(res)


def test_break_parent_cycle() -> None:
    doc = _doc([{"ref": "A1", "parent_ref": "A2"}, {"ref": "A2", "parent_ref": "A1"}])
    res = clean_document(doc)
    parents = [a.get("parent_ref") for a in res.document.activities]
    assert None in parents  # at least one edge cut
    assert res.stats["parent_cycles_broken"] >= 1
    # The remaining hierarchy is acyclic: walking parents terminates.
    by_ref = {a["ref"]: a.get("parent_ref") for a in res.document.activities}
    for start in by_ref:
        seen, cur = set(), start
        while cur is not None:
            assert cur not in seen
            seen.add(cur)
            cur = by_ref.get(cur)


def test_clamp_negative_duration() -> None:
    doc = _doc([{"ref": "A1", "duration_days": -5}])
    res = clean_document(doc)
    assert res.document.activities[0]["duration_days"] == 0
    assert "clamp_duration" in _codes(res)


def test_clamp_progress_range_and_non_numeric() -> None:
    doc = _doc(
        [
            {"ref": "A1", "progress_pct": "150"},
            {"ref": "A2", "progress_pct": "-3"},
            {"ref": "A3", "progress_pct": "oops"},
            {"ref": "A4", "progress_pct": "60"},
        ]
    )
    res = clean_document(doc)
    pcts = [a["progress_pct"] for a in res.document.activities]
    assert pcts == ["100", "0", "0", "60"]
    assert res.stats["progress_clamped"] == 3  # A4 untouched


def test_dedupe_duplicate_refs() -> None:
    doc = _doc([{"ref": "A1", "name": "first"}, {"ref": "A1", "name": "second"}])
    res = clean_document(doc)
    refs = [a["ref"] for a in res.document.activities]
    assert len(set(refs)) == 2
    assert res.stats["duplicate_refs_fixed"] == 1


def test_advisory_stats() -> None:
    doc = _doc(
        [
            {"ref": "A1", "constraint_type": "must_finish_on"},
            {"ref": "A2"},
            {"ref": "A3"},
        ],
        [
            {"predecessor_ref": "A1", "successor_ref": "A2", "relationship_type": "FS", "lag_days": -2},
            {"predecessor_ref": "A2", "successor_ref": "A3", "relationship_type": "FS", "lag_days": 0},
        ],
    )
    s = clean_document(doc).stats
    assert s["lead_count"] == 1
    assert s["hard_constraint_count"] == 1
    # A1 has no predecessor; A3 has no successor.
    assert s["activities_missing_predecessor"] == 1
    assert s["activities_missing_successor"] == 1
    assert s["activities"] == 3
    assert s["relationships"] == 2


def test_clean_is_idempotent_and_does_not_mutate_input() -> None:
    doc = _doc(
        [{"ref": "A1", "duration_days": -1, "parent_ref": "ghost"}, {"ref": "A1"}],
        [{"predecessor_ref": "A1", "successor_ref": "A1", "relationship_type": "zz", "lag_days": 0}],
    )
    before = canonicalize(doc.to_dict())
    first = clean_document(doc)
    # Input untouched (deep-copied internally).
    assert canonicalize(doc.to_dict()) == before
    # Re-cleaning the output yields no further repairs.
    second = clean_document(first.document)
    assert second.actions == []
    assert canonicalize(second.document.to_dict()) == canonicalize(first.document.to_dict())
