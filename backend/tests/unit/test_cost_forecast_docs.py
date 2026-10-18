# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Forecast documentation: the evidence threshold, the delta ladder, the comparison matrix.

Invented figures throughout; every expected value is worked out by hand in the
comment next to it.
"""

from decimal import Decimal

import pytest

from app.modules.costmodel.forecast_docs import (
    CAUSE_METHOD,
    CAUSE_NEW,
    CAUSE_REMOVED,
    CAUSE_SOURCE,
    CAUSE_VALUE,
    EvidenceThreshold,
    comparison_matrix,
    delta_ladder,
    needs_evidence,
    note_complete,
)

D = Decimal


@pytest.mark.parametrize(
    ("previous", "current", "threshold", "expected"),
    [
        # 10 % alone: 9 000 on 100 000 is 9 %, below; 11 000 is 11 %, above.
        (D("100000"), D("109000"), EvidenceThreshold(D("0"), D("10")), False),
        (D("100000"), D("111000"), EvidenceThreshold(D("0"), D("10")), True),
        # Exactly on the threshold is not above it.
        (D("100000"), D("110000"), EvidenceThreshold(D("0"), D("10")), False),
        # Both set, both must be exceeded: 3 000 is 15 % of 20 000 but below 5 000.
        (D("20000"), D("23000"), EvidenceThreshold(D("5000"), D("10")), False),
        # 15 000 is above 5 000 but only 7.5 % of 200 000.
        (D("200000"), D("215000"), EvidenceThreshold(D("5000"), D("10")), False),
        # 12 000 on 100 000: above 5 000 and above 10 %.
        (D("100000"), D("112000"), EvidenceThreshold(D("5000"), D("10")), True),
        # A drop counts the same as a rise.
        (D("100000"), D("88000"), EvidenceThreshold(D("5000"), D("10")), True),
        # A new line has no percentage: only the amount decides.
        (None, D("30000"), EvidenceThreshold(D("5000"), D("10")), True),
        (None, D("3000"), EvidenceThreshold(D("5000"), D("10")), False),
        (D("0"), D("30000"), EvidenceThreshold(D("0"), D("10")), True),
        # No threshold at all: every move needs a word.
        (D("100"), D("100.50"), EvidenceThreshold(D("0"), None), True),
        # A cent is rounding, not a move.
        (D("100"), D("100.01"), EvidenceThreshold(D("0"), None), False),
    ],
)
def test_needs_evidence(previous, current, threshold, expected) -> None:
    assert needs_evidence(previous, current, threshold) is expected


def test_a_note_is_complete_with_a_comment_and_one_piece_of_evidence() -> None:
    assert note_complete("Offer revised after site meeting", [{"kind": "minutes", "ref": "Minutes 7, item 3"}])
    assert note_complete("Offer revised", [{"kind": "document", "document_id": "4c1f", "ref": ""}])
    assert not note_complete("Offer revised", [])
    assert not note_complete("", [{"kind": "minutes", "ref": "Minutes 7"}])
    assert not note_complete("ok", [{"kind": "minutes", "ref": "Minutes 7"}])
    assert not note_complete("Offer revised", [{"kind": "other", "ref": "  "}])


def _row(key: str, forecast: str, source: str = "awarded", method: str = "best_available", code: str = "") -> dict:
    return {
        "key": key,
        "kind": "cost_line",
        "code": code or key,
        "description": "",
        "forecast": forecast,
        "source": source,
        "method": method,
    }


BEFORE = [_row("A", "100000"), _row("B", "50000"), _row("C", "20000"), _row("E", "8000")]
AFTER = [
    _row("A", "120000", source="measured"),
    _row("B", "45000"),
    _row("D", "10000", source="estimate"),
    _row("E", "8400", method="maximum", source="budget"),
]


def test_the_ladder_walks_from_the_previous_total_to_the_current_one() -> None:
    notes = {"A": ("Additional piling after soil report", [{"kind": "document", "ref": "Soil report rev B"}])}
    ladder = delta_ladder(BEFORE, AFTER, notes)
    # 100 000 + 50 000 + 20 000 + 8 000 = 178 000 before; 120 000 + 45 000 + 10 000 + 8 400 = 183 400 after.
    assert (ladder.start, ladder.end) == (D("178000"), D("183400"))
    assert [(s.key, s.delta, s.cause) for s in ladder.steps] == [
        ("A", D("20000"), CAUSE_SOURCE),
        ("C", D("-20000"), CAUSE_REMOVED),
        ("D", D("10000"), CAUSE_NEW),
        ("B", D("-5000"), CAUSE_VALUE),
        ("E", D("400"), CAUSE_METHOD),
    ]
    assert ladder.steps[0].comment == "Additional piling after soil report"
    assert ladder.steps[0].evidence == [{"kind": "document", "ref": "Soil report rev B"}]
    assert ladder.start + sum(s.delta for s in ladder.steps) + ladder.other == ladder.end


def test_small_moves_are_gathered_into_one_step() -> None:
    ladder = delta_ladder(BEFORE, AFTER, {}, min_step=D("6000"))
    assert [s.key for s in ladder.steps] == ["A", "C", "D"]
    # B -5 000 and E +400 gathered: -4 600 in two moves.
    assert (ladder.other, ladder.other_count) == (D("-4600"), 2)
    assert ladder.start + sum(s.delta for s in ladder.steps) + ladder.other == ladder.end


def test_the_ladder_keeps_the_largest_steps_when_limited() -> None:
    ladder = delta_ladder(BEFORE, AFTER, {}, limit=2)
    assert [s.key for s in ladder.steps] == ["A", "C"]
    assert (ladder.other, ladder.other_count) == (D("5400"), 3)


def test_unmoved_lines_are_not_steps() -> None:
    ladder = delta_ladder([_row("A", "100")], [_row("A", "100.00")], {})
    assert ladder.steps == [] and ladder.other == D("0") and ladder.other_count == 0


def test_the_matrix_lines_snapshots_up_side_by_side() -> None:
    columns, rows = comparison_matrix([BEFORE, AFTER])
    assert columns == [D("178000"), D("183400")]
    by_key = {r.key: r for r in rows}
    assert [r.key for r in rows] == ["A", "B", "C", "D", "E"]
    assert by_key["A"].values == [D("100000"), D("120000")]
    assert (by_key["A"].delta, by_key["A"].delta_pct) == (D("20000"), D("20.0"))
    # Absent in a snapshot is not zero: the cell stays empty, the delta counts it as nothing.
    assert by_key["C"].values == [D("20000"), None]
    assert (by_key["C"].delta, by_key["C"].delta_pct) == (D("-20000"), D("-100.0"))
    assert by_key["D"].values == [None, D("10000")]
    assert (by_key["D"].delta, by_key["D"].delta_pct) == (D("10000"), None)


def test_the_matrix_takes_three_snapshots() -> None:
    third = [_row("A", "118000"), _row("B", "45000")]
    columns, rows = comparison_matrix([BEFORE, AFTER, third])
    assert columns[-1] == D("163000")
    assert {r.key: r.delta for r in rows}["A"] == D("18000")
