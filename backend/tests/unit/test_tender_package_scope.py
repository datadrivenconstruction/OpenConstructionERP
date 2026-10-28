# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A package raised over part of a bill is compared against that part.

Both comparison screens - the leveling matrix and the budget comparison - load
the package's BOQ, which is the whole bill. A package covering a quarter of it
therefore used to put the other three quarters on the reference side, where
every bidder read as having omitted them: each out-of-scope line was imputed at
the bidder's own mean rate, so a bid of 812,400 levelled to roughly four times
that and was measured against a budget four times its own.

Two writers declare a scope and they say it differently. ``create_from_boq``
freezes the lines it chose into ``line_item_template``; the demo installer
records a plain ``scope_position_ids`` list. The reader accepts either, because
the question they answer is the same one.

Pure filtering over stub positions, so it needs no database.
"""

from __future__ import annotations

from app.modules.tendering.service import _positions_in_scope


class _Pos:
    """The one field the filter reads off a BOQ position."""

    def __init__(self, index: int) -> None:
        self.id = f"22222222-0000-0000-0000-{index:012d}"


_BILL = [_Pos(i) for i in range(12)]
_FIRST_THREE = [p.id for p in _BILL[:3]]


def test_a_declared_scope_narrows_the_reference_side() -> None:
    """The lines nobody was asked to price stay off the comparison."""
    narrowed = _positions_in_scope(_BILL, {"scope_position_ids": _FIRST_THREE})
    assert [p.id for p in narrowed] == _FIRST_THREE


def test_the_frozen_template_declares_the_same_scope() -> None:
    """``create_from_boq`` writes rows, not ids, and means the same thing."""
    template = [{"position_id": pid, "description": "x"} for pid in _FIRST_THREE]
    narrowed = _positions_in_scope(_BILL, {"line_item_template": template})
    assert [p.id for p in narrowed] == _FIRST_THREE


def test_a_package_that_declares_nothing_covers_the_whole_bill() -> None:
    """Every package created before the scope existed carries no scope."""
    assert _positions_in_scope(_BILL, {}) == _BILL
    assert _positions_in_scope(_BILL, None) == _BILL
    assert _positions_in_scope(_BILL, {"package_index": 2, "total_packages": 4}) == _BILL


def test_a_scope_that_matches_nothing_is_stale_metadata_not_an_empty_package() -> None:
    """An empty matrix would be a worse answer than a wide one.

    Ids that name no line in this BOQ mean the bill was replaced or the package
    was copied, not that the package covers no work at all.
    """
    assert _positions_in_scope(_BILL, {"scope_position_ids": ["no-such-line"]}) == _BILL
    assert _positions_in_scope(_BILL, {"scope_position_ids": []}) == _BILL
    assert _positions_in_scope(_BILL, {"line_item_template": [{"description": "no id"}]}) == _BILL


def test_metadata_of_the_wrong_shape_is_ignored_rather_than_raising() -> None:
    """Metadata is free-form JSON, so the reader cannot assume its shape."""
    assert _positions_in_scope(_BILL, {"scope_position_ids": "01.001"}) == _BILL
    assert _positions_in_scope(_BILL, {"line_item_template": "frozen"}) == _BILL
    assert _positions_in_scope(_BILL, {"line_item_template": ["not a mapping"]}) == _BILL


def test_a_scope_that_half_matches_keeps_the_half_that_does() -> None:
    """One line deleted from the bill does not widen the package back out."""
    meta = {"scope_position_ids": [_BILL[0].id, "deleted-since"]}
    assert [p.id for p in _positions_in_scope(_BILL, meta)] == [_BILL[0].id]
