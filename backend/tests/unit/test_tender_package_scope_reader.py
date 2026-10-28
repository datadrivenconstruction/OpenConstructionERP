# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The sections a package was raised over can be read, not only computed.

``create_from_boq`` has recorded ``source_section_ids`` in the package metadata
since it was written, and nothing has ever read it back. The comparison and
levelling screens narrow to that scope, so the number a bidder is measured
against already depends on it, but the reader could not see which part of the
bill was in play: a package over one trade looked exactly like a package over
the whole thing.

Two writers declare a scope and they say it differently, which is why the
derivation exists. ``create_from_boq`` names the sections; the demo installer
records a flat position list. When only the flat list is there the sections are
derived by walking each in-scope position up to its top-level ancestor, and the
answer says it was derived rather than recorded.

Pure over stub positions, so it needs no database, the same as the filter it
sits beside.
"""

from __future__ import annotations

from app.modules.tendering.service import _scope_sections


class _Pos:
    """The fields the reader takes off a BOQ position."""

    def __init__(self, index: int, parent: str | None = None, ordinal: str = "", description: str = "") -> None:
        self.id = f"33333333-0000-0000-0000-{index:012d}"
        self.parent_id = parent
        self.ordinal = ordinal
        self.description = description


_ROHBAU = _Pos(1, None, "01", "Rohbau")
_DACH = _Pos(2, None, "02", "Dachabdichtung")
_AUSBAU = _Pos(3, None, "03", "Ausbau")
_BILL = [
    _ROHBAU,
    _DACH,
    _AUSBAU,
    *[_Pos(10 + i, _ROHBAU.id, f"01.{i:02d}") for i in range(4)],
    *[_Pos(20 + i, _DACH.id, f"02.{i:02d}") for i in range(3)],
    *[_Pos(30 + i, _AUSBAU.id, f"03.{i:02d}") for i in range(5)],
]
_DACH_LINES = [p.id for p in _BILL if p.parent_id == _DACH.id]


def test_the_recorded_sections_are_reported_as_recorded() -> None:
    """The metadata names the sections, so nothing has to be inferred."""
    described = _scope_sections(
        _BILL,
        {
            "source_section_ids": [_DACH.id],
            "line_item_template": [{"position_id": pid} for pid in [_DACH.id, *_DACH_LINES]],
        },
    )
    assert described["sections_recorded"] is True
    assert [s["ordinal"] for s in described["sections"]] == ["02"]
    assert described["sections"][0]["description"] == "Dachabdichtung"
    # The section itself plus its three lines.
    assert described["sections"][0]["position_count"] == 4
    assert described["included_position_count"] == 4
    assert described["covers_whole_bill"] is False


def test_a_flat_scope_still_names_the_section_it_belongs_to() -> None:
    """The demo installer writes positions, not sections, and means the same."""
    described = _scope_sections(_BILL, {"scope_position_ids": _DACH_LINES})
    assert described["sections_recorded"] is False
    assert [s["ordinal"] for s in described["sections"]] == ["02"]
    assert described["sections"][0]["position_count"] == 3
    assert described["covers_whole_bill"] is False


def test_a_package_that_declares_nothing_covers_the_whole_bill() -> None:
    """Every package created before the scope existed carries no scope."""
    described = _scope_sections(_BILL, {})
    assert described["covers_whole_bill"] is True
    assert described["included_position_count"] == len(_BILL)
    assert [s["ordinal"] for s in described["sections"]] == ["01", "02", "03"]
    assert sum(s["position_count"] for s in described["sections"]) == len(_BILL)


def test_a_scope_naming_every_line_is_not_reported_as_partial() -> None:
    """A package over all three trades is a whole-bill package."""
    described = _scope_sections(_BILL, {"scope_position_ids": [p.id for p in _BILL]})
    assert described["covers_whole_bill"] is True
    assert len(described["sections"]) == 3


def test_stale_section_ids_fall_back_to_deriving_them() -> None:
    """Ids that name nothing in this bill mean the bill was replaced.

    Reporting them as recorded would print empty rows for sections that no
    longer exist, so the derivation takes over and says it did.
    """
    described = _scope_sections(
        _BILL,
        {"source_section_ids": ["44444444-0000-0000-0000-000000000009"], "scope_position_ids": _DACH_LINES},
    )
    assert described["sections_recorded"] is False
    assert [s["ordinal"] for s in described["sections"]] == ["02"]


def test_a_scope_spanning_two_trades_names_both() -> None:
    described = _scope_sections(_BILL, {"scope_position_ids": [*_DACH_LINES, _BILL[3].id]})
    assert [s["ordinal"] for s in described["sections"]] == ["01", "02"]
    assert [s["position_count"] for s in described["sections"]] == [1, 3]
