"""Next WBS code in a section and the slot a new child takes in the flat order."""

from __future__ import annotations

import uuid

import pytest

from app.modules.schedule.wbs_numbering import (
    effective_code,
    next_wbs_code,
    order_with_block_under,
    sort_order_changes,
    subtree_ids,
    suggest_code,
    tree_order,
)


@pytest.mark.parametrize(
    ("parent", "siblings", "expected"),
    [
        ("2", ["2.1", "2.2"], "2.3"),
        # Natural order, not text order: 2.10 is after 2.9.
        ("2", ["2.1", "2.9", "2.10"], "2.11"),
        # BOQ-generated sections are zero padded and keep the padding.
        ("01", ["01.001", "01.002"], "01.003"),
        ("2.1", [], "2.1.1"),
        # A sibling from a neighbouring section that merely shares the first
        # digit is not part of this sequence.
        ("2", ["2.1", "20.7"], "2.2"),
        # Siblings without the parent prefix still carry a sequence to continue.
        ("300", ["310", "320"], "321"),
        # A sibling code without a trailing number is ignored.
        ("3", ["3.1", "note"], "3.2"),
    ],
)
def test_next_code_continues_the_section(parent: str, siblings: list[str], expected: str) -> None:
    assert next_wbs_code(parent, siblings, siblings, has_parent=True) == expected


def test_section_without_a_code_gets_no_suggestion() -> None:
    assert next_wbs_code("", ["1", "2"], ["1", "2"], has_parent=True) == ""


def test_top_level_continues_the_root_numbering() -> None:
    assert next_wbs_code(None, ["1", "2", "3"], ["1", "2", "3", "1.1"], has_parent=False) == "4"
    assert next_wbs_code(None, [], [], has_parent=False) == "1"


def test_suggestion_skips_a_code_used_elsewhere_in_the_schedule() -> None:
    # 2.3 exists under another parent (a hand-typed duplicate), so the next
    # free code in the sequence is offered instead.
    assert next_wbs_code("2", ["2.1", "2.2"], ["2", "2.1", "2.2", "2.3"], has_parent=True) == "2.4"


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def _place(new_id, parent, outline):
    planned = [*outline, (new_id, parent, 2**31 - 1, "")]
    return order_with_block_under(new_id, parent, planned), planned


def test_new_child_goes_after_the_last_descendant_of_its_section() -> None:
    s1, a, a1, s2, b, new = _ids(6)
    outline = [
        (s1, None, 1, "1"),
        (a, s1, 2, "1.1"),
        (a1, a, 3, "1.1.1"),
        (s2, None, 4, "2"),
        (b, s2, 5, "2.1"),
    ]
    assert subtree_ids(s1, outline) == {s1, a, a1}
    order, planned = _place(new, s1, outline)
    # Right after 1.1.1 and before section 2, not at the bottom.
    assert order == [s1, a, a1, new, s2, b]
    # Positions become the new sort orders; rows already at theirs are not
    # rewritten.
    assert sort_order_changes(order, planned) == {s1: 0, a: 1, a1: 2, new: 3}


def test_legacy_schedule_with_every_sort_order_zero_is_placed_by_the_tree() -> None:
    # Seeded and imported schedules carry the column default everywhere, so
    # sort_order alone says nothing; the tree and the codes decide.
    s1, a, s2, b, new = _ids(5)
    outline = [(s2, None, 0, "2"), (b, s2, 0, "2.1"), (a, s1, 0, "1.1"), (s1, None, 0, "1")]
    assert tree_order(outline) == [s1, a, s2, b]
    order, planned = _place(new, s1, outline)
    assert order == [s1, a, new, s2, b]
    assert sort_order_changes(order, planned) == {a: 1, new: 2, s2: 3, b: 4}


def test_moving_an_activity_takes_its_children_to_the_end_of_the_new_section() -> None:
    s1, a, a1, s2, b = _ids(5)
    outline = [(s1, None, 0, "1"), (a, s1, 1, "1.1"), (a1, a, 2, "1.1.1"), (s2, None, 3, "2"), (b, s2, 4, "2.1")]
    moved = [(aid, s2 if aid == a else pid, o, c) for aid, pid, o, c in outline]
    assert order_with_block_under(a, s2, moved) == [s1, s2, b, a, a1]
    to_top = [(aid, None if aid == b else pid, o, c) for aid, pid, o, c in outline]
    assert order_with_block_under(b, None, to_top) == [s1, a, a1, s2, b]


def test_a_section_without_a_code_numbers_its_children_by_position() -> None:
    s1, s2, x = _ids(3)
    outline = [(s1, None, 0, "1"), (s2, None, 1, ""), (x, s2, 2, "")]
    assert effective_code(s2, outline) == "2"
    assert effective_code(x, outline) == "2.1"
    # The uncoded first child sits at 2.1, so the next one is 2.2.
    assert suggest_code(s2, outline) == "2.2"


def test_top_level_suggestion_without_a_section() -> None:
    s1, s2 = _ids(2)
    assert suggest_code(None, [(s1, None, 0, "1"), (s2, None, 1, "2")]) == "3"
    assert suggest_code(None, []) == "1"
