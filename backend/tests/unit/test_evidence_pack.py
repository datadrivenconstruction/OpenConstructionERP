# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure claims / dispute evidence-pack engine.

These exercise :mod:`app.modules.claims_evidence.evidence_pack` directly with
plain dataclass inputs - no database, FastAPI or ORM - so they run on any
interpreter (including the local Python 3.11 runner), exactly like the other
pure-engine tests in this suite.

They lock in the contract the evidence-pack feature depends on: forgiving ISO
parsing, identity-based dedupe, chronological ordering with undated entries
last, canonical section grouping with empty sections omitted, the date span,
and a deterministic content digest that is stable across input permutations
and changes when the entry set changes.
"""

from __future__ import annotations

import hashlib

import pytest

from app.modules.claims_evidence import evidence_pack as ep
from app.modules.claims_evidence.evidence_pack import (
    EvidenceEntry,
    EvidencePack,
    EvidenceSection,
)


def _entry(
    ref_id: str,
    source_module: str,
    kind: str,
    occurred_at: str | None,
    *,
    title: str = "",
    actor_id: str | None = None,
    summary: str = "",
) -> EvidenceEntry:
    """Build an EvidenceEntry with a sensible default title."""
    return EvidenceEntry(
        ref_id=ref_id,
        source_module=source_module,
        kind=kind,
        title=title or f"{source_module}:{ref_id}",
        occurred_at=occurred_at,
        actor_id=actor_id,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# parse_iso
# ---------------------------------------------------------------------------


def test_parse_iso_none_and_blank_return_none() -> None:
    assert ep.parse_iso(None) is None
    assert ep.parse_iso("") is None
    assert ep.parse_iso("   ") is None


def test_parse_iso_garbage_returns_none() -> None:
    assert ep.parse_iso("not-a-date") is None
    assert ep.parse_iso("2026-13-99") is None


def test_parse_iso_accepts_trailing_z_as_utc() -> None:
    dt = ep.parse_iso("2026-06-24T10:30:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 6, 24, 10, 30)


def test_parse_iso_date_only_falls_back_to_midnight_utc() -> None:
    dt = ep.parse_iso("2026-06-24")
    assert dt is not None
    assert (dt.hour, dt.minute, dt.second) == (0, 0, 0)
    assert dt.utcoffset().total_seconds() == 0


def test_parse_iso_naive_is_assumed_utc() -> None:
    dt = ep.parse_iso("2026-06-24T08:00:00")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_iso_aware_offset_is_converted_to_utc() -> None:
    # 12:00 at +02:00 is 10:00 UTC.
    dt = ep.parse_iso("2026-06-24T12:00:00+02:00")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 0
    assert (dt.hour, dt.minute) == (10, 0)


# ---------------------------------------------------------------------------
# section_for
# ---------------------------------------------------------------------------


def test_section_for_routes_by_module() -> None:
    assert ep.section_for(_entry("n1", "notices", "x", None)) == "notices"
    assert ep.section_for(_entry("c1", "correspondence", "x", None)) == "correspondence"
    assert ep.section_for(_entry("r1", "rfis", "x", None)) == "rfis"
    assert ep.section_for(_entry("v1", "changeorders", "x", None)) == "variations"
    assert ep.section_for(_entry("a1", "approval_routes", "x", None)) == "approvals"
    assert ep.section_for(_entry("d1", "forensic_delay", "x", None)) == "delay"
    assert ep.section_for(_entry("t1", "activity_log", "x", None)) == "timeline"


def test_section_for_module_is_case_insensitive() -> None:
    assert ep.section_for(_entry("n1", "Notices", "x", None)) == "notices"
    assert ep.section_for(_entry("n2", "  NOTICES  ", "x", None)) == "notices"


def test_section_for_falls_back_to_kind_when_module_unknown() -> None:
    # Unknown module, but the kind carries the signal.
    assert ep.section_for(_entry("x1", "feed", "delay_notice", None)) == "notices"
    assert ep.section_for(_entry("x2", "feed", "rfi_response", None)) == "rfis"
    assert ep.section_for(_entry("x3", "feed", "variation_request", None)) == "variations"
    assert ep.section_for(_entry("x4", "feed", "outgoing_letter", None)) == "correspondence"
    assert ep.section_for(_entry("x5", "feed", "eot_claim", None)) == "delay"


def test_section_for_unknown_everything_is_other() -> None:
    assert ep.section_for(_entry("u1", "mystery", "whatever", None)) == "other"
    assert ep.section_for(_entry("u2", "", "", None)) == "other"


def test_section_for_module_wins_over_kind() -> None:
    # Explicit notices module beats an rfi-shaped kind.
    assert ep.section_for(_entry("p1", "notices", "rfi", None)) == "notices"


def test_section_for_always_returns_a_known_section() -> None:
    entry = _entry("z", "anything", "anything", None)
    assert ep.section_for(entry) in ep.SECTION_ORDER


# ---------------------------------------------------------------------------
# assemble_pack: ordering
# ---------------------------------------------------------------------------


def test_chronological_ordering_with_none_dated_last() -> None:
    entries = [
        _entry("b", "timeline", "event", "2026-06-10T00:00:00Z"),
        _entry("nodate", "timeline", "event", None),
        _entry("a", "timeline", "event", "2026-06-01T00:00:00Z"),
        _entry("c", "timeline", "event", "2026-06-20T00:00:00Z"),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    # Single section (timeline); inspect its order.
    assert [s.name for s in pack.sections] == ["timeline"]
    ordered_refs = [e.ref_id for e in pack.sections[0].entries]
    assert ordered_refs == ["a", "b", "c", "nodate"]


def test_undated_entries_tiebreak_deterministically() -> None:
    # Two undated entries: order must follow (source_module, ref_id).
    entries = [
        _entry("z", "timeline", "event", None),
        _entry("a", "timeline", "event", None),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    refs = [e.ref_id for e in pack.sections[0].entries]
    assert refs == ["a", "z"]


def test_equal_dates_tiebreak_by_module_then_ref() -> None:
    same = "2026-06-05T09:00:00Z"
    entries = [
        _entry("2", "timeline", "event", same),
        _entry("1", "timeline", "event", same),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    refs = [e.ref_id for e in pack.sections[0].entries]
    assert refs == ["1", "2"]


# ---------------------------------------------------------------------------
# assemble_pack: dedupe
# ---------------------------------------------------------------------------


def test_dedupe_keeps_first_occurrence() -> None:
    entries = [
        _entry("dup", "notices", "notice", "2026-06-01T00:00:00Z", title="first"),
        _entry("dup", "notices", "notice", "2026-06-02T00:00:00Z", title="second"),
        _entry("other", "notices", "notice", "2026-06-03T00:00:00Z"),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    assert pack.entry_count == 2
    notices = pack.sections[0]
    titles = {e.title for e in notices.entries}
    assert "first" in titles
    assert "second" not in titles


def test_same_ref_different_module_not_deduped() -> None:
    entries = [
        _entry("X", "notices", "notice", "2026-06-01T00:00:00Z"),
        _entry("X", "rfis", "rfi", "2026-06-02T00:00:00Z"),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    assert pack.entry_count == 2


# ---------------------------------------------------------------------------
# assemble_pack: section grouping
# ---------------------------------------------------------------------------


def test_sections_follow_canonical_order_and_omit_empty() -> None:
    # Provide entries out of canonical order; expect canonical order back and
    # only the populated sections.
    entries = [
        _entry("t1", "timeline", "event", "2026-06-04T00:00:00Z"),
        _entry("a1", "approvals", "approval", "2026-06-03T00:00:00Z"),
        _entry("n1", "notices", "notice", "2026-06-01T00:00:00Z"),
        _entry("r1", "rfis", "rfi", "2026-06-02T00:00:00Z"),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    assert [s.name for s in pack.sections] == [
        "notices",
        "rfis",
        "approvals",
        "timeline",
    ]
    # "correspondence", "variations", "delay", "other" are absent.
    present = {s.name for s in pack.sections}
    assert "correspondence" not in present
    assert "other" not in present


def test_within_section_chronological_order_preserved() -> None:
    entries = [
        _entry("late", "correspondence", "email", "2026-06-20T00:00:00Z"),
        _entry("early", "correspondence", "email", "2026-06-01T00:00:00Z"),
        _entry("mid", "correspondence", "email", "2026-06-10T00:00:00Z"),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    assert len(pack.sections) == 1
    refs = [e.ref_id for e in pack.sections[0].entries]
    assert refs == ["early", "mid", "late"]


# ---------------------------------------------------------------------------
# assemble_pack: date span
# ---------------------------------------------------------------------------


def test_date_from_and_to_are_original_strings_of_extremes() -> None:
    entries = [
        _entry("b", "timeline", "event", "2026-06-10T12:00:00Z"),
        _entry("a", "timeline", "event", "2026-06-01"),  # date-only earliest
        _entry("nodate", "timeline", "event", None),
        _entry("c", "timeline", "event", "2026-06-20T23:59:00+00:00"),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    assert pack.date_from == "2026-06-01"
    assert pack.date_to == "2026-06-20T23:59:00+00:00"


def test_date_span_none_when_no_entry_parses() -> None:
    entries = [
        _entry("a", "timeline", "event", None),
        _entry("b", "timeline", "event", "garbage"),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    assert pack.date_from is None
    assert pack.date_to is None
    # Both still included.
    assert pack.entry_count == 2


def test_offset_aware_extreme_compares_correctly() -> None:
    # 2026-06-02T00:30:00+02:00 == 2026-06-01T22:30 UTC, which is EARLIER than
    # 2026-06-01T23:00:00Z, so the offset-aware entry must win date_from.
    entries = [
        _entry("zulu", "timeline", "event", "2026-06-01T23:00:00Z"),
        _entry("plus2", "timeline", "event", "2026-06-02T00:30:00+02:00"),
    ]
    pack = ep.assemble_pack("CLM-1", entries)
    assert pack.date_from == "2026-06-02T00:30:00+02:00"
    assert pack.date_to == "2026-06-01T23:00:00Z"


# ---------------------------------------------------------------------------
# assemble_pack: content digest
# ---------------------------------------------------------------------------


def test_digest_is_stable_across_input_orderings() -> None:
    a = _entry("a", "notices", "notice", "2026-06-01T00:00:00Z")
    b = _entry("b", "rfis", "rfi", "2026-06-02T00:00:00Z")
    c = _entry("c", "timeline", "event", None)
    pack1 = ep.assemble_pack("CLM-1", [a, b, c])
    pack2 = ep.assemble_pack("CLM-1", [c, b, a])
    pack3 = ep.assemble_pack("CLM-1", [b, c, a])
    assert pack1.content_digest == pack2.content_digest == pack3.content_digest


def test_digest_changes_when_entry_added() -> None:
    a = _entry("a", "notices", "notice", "2026-06-01T00:00:00Z")
    b = _entry("b", "rfis", "rfi", "2026-06-02T00:00:00Z")
    base = ep.assemble_pack("CLM-1", [a])
    more = ep.assemble_pack("CLM-1", [a, b])
    assert base.content_digest != more.content_digest


def test_digest_changes_when_date_changes() -> None:
    a1 = _entry("a", "notices", "notice", "2026-06-01T00:00:00Z")
    a2 = _entry("a", "notices", "notice", "2026-06-02T00:00:00Z")
    p1 = ep.assemble_pack("CLM-1", [a1])
    p2 = ep.assemble_pack("CLM-1", [a2])
    assert p1.content_digest != p2.content_digest


def test_digest_matches_hand_computed_canonical_blob() -> None:
    a = _entry("a", "notices", "notice", "2026-06-01T00:00:00Z")
    b = _entry("b", "timeline", "event", None)
    pack = ep.assemble_pack("CLM-1", [b, a])
    # Final order: a (dated) then b (undated). Canonical lines:
    expected_blob = "a|notices|notice|2026-06-01T00:00:00Z\nb|timeline|event|"
    expected = hashlib.sha256(expected_blob.encode("utf-8")).hexdigest()
    assert pack.content_digest == expected


def test_digest_ignores_non_identity_fields() -> None:
    # title / actor_id / summary are not part of the digest line.
    a1 = _entry("a", "notices", "notice", "2026-06-01T00:00:00Z", title="one", summary="s1")
    a2 = _entry("a", "notices", "notice", "2026-06-01T00:00:00Z", title="two", actor_id="u9", summary="s2")
    p1 = ep.assemble_pack("CLM-1", [a1])
    p2 = ep.assemble_pack("CLM-1", [a2])
    assert p1.content_digest == p2.content_digest


# ---------------------------------------------------------------------------
# assemble_pack: empty input + basis
# ---------------------------------------------------------------------------


def test_empty_input_is_stable_and_empty() -> None:
    pack = ep.assemble_pack("CLM-1", [])
    assert isinstance(pack, EvidencePack)
    assert pack.entry_count == 0
    assert pack.sections == []
    assert pack.date_from is None
    assert pack.date_to is None
    assert pack.basis == "dispute"
    # Digest of the empty pack is the SHA-256 of the empty string.
    assert pack.content_digest == hashlib.sha256(b"").hexdigest()


def test_basis_is_carried_through() -> None:
    pack = ep.assemble_pack("CLM-2", [], basis="variation")
    assert pack.subject_ref == "CLM-2"
    assert pack.basis == "variation"


def test_returned_types_are_dataclasses() -> None:
    a = _entry("a", "notices", "notice", "2026-06-01T00:00:00Z")
    pack = ep.assemble_pack("CLM-1", [a])
    assert isinstance(pack, EvidencePack)
    assert all(isinstance(s, EvidenceSection) for s in pack.sections)
    assert all(isinstance(e, EvidenceEntry) for s in pack.sections for e in s.entries)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
