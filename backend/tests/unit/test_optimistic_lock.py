# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure tests for the optimistic-lock helpers used by offline field sync​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.offline_merge import clean_client_op_id
from app.core.optimistic_lock import (
    bump,
    check_version,
    parse_if_match,
    resolve_expected_version,
    three_way_merge,
    unresolved_conflicts,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [('"3"', 3), ("3", 3), ('W/"3"', 3), (' W/"12" ', 12), (None, None), ("", None), ("*", None)],
)
def test_parse_if_match_accepts_the_usual_spellings(header: str | None, expected: int | None) -> None:
    assert parse_if_match(header) == expected


@pytest.mark.parametrize("header", ["abc", '"3a"', "-1", '"1","2"'])
def test_parse_if_match_rejects_garbage_with_400(header: str) -> None:
    with pytest.raises(HTTPException) as exc:
        parse_if_match(header)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_if_match"


def test_header_wins_over_body_and_a_disagreement_is_refused() -> None:
    assert resolve_expected_version('"2"', None) == 2
    assert resolve_expected_version(None, 4) == 4
    assert resolve_expected_version('"2"', 2) == 2
    assert resolve_expected_version(None, None) is None
    with pytest.raises(HTTPException) as exc:
        resolve_expected_version('"2"', 3)
    assert exc.value.status_code == 400


def test_check_version_passes_when_current_or_unconditional() -> None:
    check_version(3, 3, {})
    check_version(3, None, {})


def test_check_version_409_carries_the_current_row() -> None:
    payload = {"id": "x", "notes": "server text", "version": 5}
    with pytest.raises(HTTPException) as exc:
        check_version(5, 3, payload)
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["code"] == "version_conflict"
    assert detail["current_version"] == 5
    assert detail["current"] == payload
    assert "version 3" in detail["message"]
    assert "5" in detail["message"]


def test_bump_increments_and_treats_missing_as_one() -> None:
    obj = SimpleNamespace(version=3)
    assert bump(obj) == 4
    assert obj.version == 4
    blank = SimpleNamespace(version=None)
    assert bump(blank) == 2


LONG = {"notes"}
LISTS = {"checklist"}


def test_merge_takes_the_side_that_changed() -> None:
    base = {"notes": "a", "crew": 5, "weather": "dry"}
    mine = {"notes": "a", "crew": 8, "weather": "dry"}
    theirs = {"notes": "a2", "crew": 5, "weather": "dry"}
    out = three_way_merge(base, mine, theirs, LONG, LISTS)
    assert out["merged"] == {"notes": "a2", "crew": 8, "weather": "dry"}
    assert sorted(out["auto_fields"]) == ["crew", "notes"]
    assert out["conflicts"] == []


def test_merge_simple_field_changed_on_both_sides_is_last_writer_wins() -> None:
    out = three_way_merge({"crew": 5}, {"crew": 8}, {"crew": 6}, LONG, LISTS)
    assert out["merged"]["crew"] == 8
    assert out["auto_fields"] == ["crew"]
    assert out["conflicts"] == []


def test_merge_same_change_on_both_sides_is_not_a_conflict_even_for_long_text() -> None:
    out = three_way_merge({"notes": "a"}, {"notes": "b"}, {"notes": "b"}, LONG, LISTS)
    assert out["merged"]["notes"] == "b"
    assert out["conflicts"] == []


def test_merge_long_text_changed_differently_is_a_conflict_and_keeps_theirs() -> None:
    out = three_way_merge({"notes": "a"}, {"notes": "mine"}, {"notes": "theirs"}, LONG, LISTS)
    assert out["conflicts"] == ["notes"]
    assert out["merged"]["notes"] == "theirs"
    assert "notes" not in out["auto_fields"]


def test_merge_list_changed_differently_is_a_conflict() -> None:
    base = {"checklist": [{"id": 1, "response": None}]}
    mine = {"checklist": [{"id": 1, "response": "pass"}]}
    theirs = {"checklist": [{"id": 1, "response": "fail"}]}
    out = three_way_merge(base, mine, theirs, LONG, LISTS)
    assert out["conflicts"] == ["checklist"]


def test_merge_untouched_fields_are_neither_auto_nor_conflicted() -> None:
    out = three_way_merge({"a": 1}, {"a": 1}, {"a": 1}, LONG, LISTS)
    assert out == {"merged": {"a": 1}, "auto_fields": [], "conflicts": []}


def test_unresolved_conflicts_needs_a_valid_side() -> None:
    assert unresolved_conflicts(["notes", "checklist"], {"notes": "mine"}) == ["checklist"]
    assert unresolved_conflicts(["notes"], {"notes": "later"}) == ["notes"]
    assert unresolved_conflicts(["notes"], {"notes": "manual"}) == []
    assert unresolved_conflicts([], {}) == []


def test_client_op_id_must_be_plain() -> None:
    assert clean_client_op_id("dev1-0001") == "dev1-0001"
    assert clean_client_op_id("a" * 65) is None
    assert clean_client_op_id("bad id%") is None
    assert clean_client_op_id(None) is None


def test_merge_complete_rule_flags_each_unresolved_field() -> None:
    from app.core.validation.rules import OfflineSyncMergeComplete

    class _Ctx:
        data = {"conflicts": ["notes", "photo_ids"], "resolutions": {"notes": "theirs"}}
        metadata = {"locale": "en"}

    results = asyncio.run(OfflineSyncMergeComplete().validate(_Ctx()))  # type: ignore[arg-type]
    assert [r.element_ref for r in results] == ["photo_ids"]
    assert results[0].passed is False
    assert "photo_ids" in results[0].message
    assert "{field}" not in results[0].message

    _Ctx.data = {"conflicts": ["notes"], "resolutions": {"notes": "manual"}}
    assert asyncio.run(OfflineSyncMergeComplete().validate(_Ctx())) == []  # type: ignore[arg-type]
