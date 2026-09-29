"""Next WBS code in a section and the slot a new child takes in the flat order."""

from __future__ import annotations

import uuid

import pytest

from app.modules.schedule.wbs_numbering import insert_position_under, next_wbs_code, subtree_ids


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


def test_new_child_goes_after_the_last_descendant_of_its_section() -> None:
    s1, a, a1, s2, b = _ids(5)
    outline = [
        (s1, None, 1, "1"),
        (a, s1, 2, "1.1"),
        (a1, a, 3, "1.1.1"),
        (s2, None, 4, "2"),
        (b, s2, 5, "2.1"),
    ]
    assert subtree_ids(s1, outline) == {s1, a, a1}
    # Right after 1.1.1 and before section 2, not at the bottom (6).
    assert insert_position_under(s1, outline) == 4
    assert insert_position_under(s2, outline) == 6


def test_empty_section_takes_the_slot_after_itself() -> None:
    s1, s2 = _ids(2)
    outline = [(s1, None, 1, "1"), (s2, None, 2, "2")]
    assert insert_position_under(s1, outline) == 2
