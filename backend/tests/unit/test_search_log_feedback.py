# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the v2936 search-log user-feedback hook.

Two pieces under test:

* ``_derive_picked_rank_and_code`` — pure helper that finds the user's
  pick inside the stored ``MatchGroup.methods`` JSON.
* ``_record_pick_to_search_log`` — DB hook that writes
  ``picked_rank`` / ``picked_rate_code`` / ``picked_at`` onto the most
  recent ``oe_match_elements_search_log`` row for the (session, group)
  pair.

The end-to-end /confirm path is covered separately by the broader
match_elements integration tests; here we only need the wiring to be
right.
"""

from __future__ import annotations

import uuid

from app.modules.match_elements.service import _derive_picked_rank_and_code

# ── _derive_picked_rank_and_code — happy path + edge cases ──────────────


def test_derive_picked_rank_finds_first_candidate() -> None:
    """User picked the top suggestion — rank 1, code from that row."""
    cid = uuid.uuid4()
    methods = {
        "vector": [
            {"id": str(cid), "code": "FER46-01-001"},
            {"id": str(uuid.uuid4()), "code": "FER46-01-002"},
            {"id": str(uuid.uuid4()), "code": "FER46-01-003"},
        ],
    }
    rank, code = _derive_picked_rank_and_code(
        methods,
        chosen_method="vector",
        chosen_candidate_id=cid,
    )
    assert rank == 1
    assert code == "FER46-01-001"


def test_derive_picked_rank_finds_third_candidate() -> None:
    """Operator confirmed the third suggestion — rank 3."""
    cids = [uuid.uuid4() for _ in range(5)]
    target = cids[2]
    methods = {
        "vector": [
            {"id": str(cids[0]), "code": "A"},
            {"id": str(cids[1]), "code": "B"},
            {"id": str(target), "code": "C"},
            {"id": str(cids[3]), "code": "D"},
            {"id": str(cids[4]), "code": "E"},
        ],
    }
    rank, code = _derive_picked_rank_and_code(
        methods,
        chosen_method="vector",
        chosen_candidate_id=target,
    )
    assert rank == 3
    assert code == "C"


def test_derive_picked_rank_returns_none_for_manual_override() -> None:
    """If the chosen candidate isn't in the suggested list (manual
    override / user typed a custom rate), return (None, None) so the
    log row keeps NULL — analytics can then split "picked from
    suggestions" vs "manual override"."""
    methods = {
        "vector": [
            {"id": str(uuid.uuid4()), "code": "A"},
            {"id": str(uuid.uuid4()), "code": "B"},
        ],
    }
    rank, code = _derive_picked_rank_and_code(
        methods,
        chosen_method="vector",
        chosen_candidate_id=uuid.uuid4(),
    )
    assert rank is None
    assert code is None


def test_derive_picked_rank_handles_missing_chosen_method() -> None:
    """``chosen_method=None`` (legacy / no method recorded) → (None, None)
    instead of crashing on a KeyError."""
    rank, code = _derive_picked_rank_and_code(
        {"vector": [{"id": "x", "code": "A"}]},
        chosen_method=None,
        chosen_candidate_id=uuid.uuid4(),
    )
    assert (rank, code) == (None, None)


def test_derive_picked_rank_handles_missing_methods_dict() -> None:
    """When MatchGroup.methods is None / empty (group never matched),
    return (None, None) — no crash, no false rank."""
    cid = uuid.uuid4()
    assert _derive_picked_rank_and_code(
        None,
        chosen_method="vector",
        chosen_candidate_id=cid,
    ) == (None, None)
    assert _derive_picked_rank_and_code(
        {},
        chosen_method="vector",
        chosen_candidate_id=cid,
    ) == (None, None)


def test_derive_picked_rank_skips_non_dict_entries() -> None:
    """Defensive: corrupt JSON could store a list of strings instead of
    candidate dicts. Don't crash — just skip and return (None, None)."""
    cid = uuid.uuid4()
    methods = {
        "vector": ["not-a-dict", 42, None, {"id": str(cid), "code": "GOOD"}],
    }
    rank, code = _derive_picked_rank_and_code(
        methods,
        chosen_method="vector",
        chosen_candidate_id=cid,
    )
    # Index 4 (1-based) — the only valid dict matching the cid.
    assert rank == 4
    assert code == "GOOD"


def test_derive_picked_rank_handles_chosen_method_not_in_methods() -> None:
    """User picked via 'manual' but only 'vector' results were stored —
    no match possible, return (None, None)."""
    cid = uuid.uuid4()
    methods = {
        "vector": [{"id": str(cid), "code": "A"}],
    }
    rank, code = _derive_picked_rank_and_code(
        methods,
        chosen_method="lexical",
        chosen_candidate_id=cid,
    )
    assert (rank, code) == (None, None)
