"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The clash package defines "open" twice, for two different questions (#187).

``clash.schemas.OPEN_STATUSES`` answers "which ``ClashResult.status`` values
still need attention" and is drawn from ``CLASH_STATUSES``. It is what every
``ClashResult`` query filters by.

``clash.risk_matrix.OPEN_RESULT_OR_ISSUE_STATUSES`` answers a wider question:
``risk_matrix`` is a pure, DB-free module handed plain ``ClashScheduleFacts``,
so it cannot tell whether a ``status`` came off a ``ClashResult`` row or off a
smart ``ClashIssue`` (``CLASH_ISSUE_STATUSES``, whose open states are ``new``
and ``persisted``). Its set is the union of both vocabularies.

The two therefore are not duplication, and merging them would be wrong in
either direction: narrowing the risk set to the row set would drop a
``persisted`` issue, and widening the row filter to the union would put
``persisted`` into a SQL ``IN`` clause against a column that can never hold
it. They only ever looked like duplication because both were called
``OPEN_STATUSES``.

These tests pin each set to its own vocabulary and pin the containment that
has to hold between them, so a future edit to either one cannot silently
drift. Modelled on ``tests/unit/test_back_charge_status_enum.py``.
"""

from __future__ import annotations

from app.modules.clash.risk_matrix import OPEN_RESULT_OR_ISSUE_STATUSES, is_open_status
from app.modules.clash.schemas import CLASH_ISSUE_STATUSES, CLASH_STATUSES, OPEN_STATUSES


def test_the_result_open_set_is_drawn_from_the_result_vocabulary() -> None:
    """Every value the ClashResult filter uses is a value the column can hold."""
    assert set(OPEN_STATUSES) <= set(CLASH_STATUSES)


def test_the_risk_open_set_is_drawn_from_the_two_vocabularies_it_spans() -> None:
    """The risk-matrix set adds nothing that neither clash model can produce."""
    known = set(CLASH_STATUSES) | set(CLASH_ISSUE_STATUSES)
    assert OPEN_RESULT_OR_ISSUE_STATUSES - known == set()


def test_the_risk_open_set_covers_every_open_result_status() -> None:
    """The union must not drop a status the row-level filter calls open.

    ``build_project_risk_matrix`` feeds the matrix rows that a
    ``ClashResult.status IN OPEN_STATUSES`` query already selected. If the
    risk set ever stopped covering that set, those rows would be fetched and
    then silently discarded, and the risk matrix would under-report.
    """
    assert set(OPEN_STATUSES) <= OPEN_RESULT_OR_ISSUE_STATUSES


def test_the_two_sets_are_genuinely_different() -> None:
    """They are not copies - if they ever converge, one of them lost a case.

    ``persisted`` is the difference: it is a smart-issue state, absent from
    ``CLASH_STATUSES``, and it is the whole reason the risk-matrix module
    keeps its own wider set instead of importing the schemas one.
    """
    assert OPEN_RESULT_OR_ISSUE_STATUSES - set(OPEN_STATUSES) == {"persisted"}
    assert "persisted" not in CLASH_STATUSES
    assert "persisted" in CLASH_ISSUE_STATUSES


def test_a_closed_status_from_either_vocabulary_is_not_open() -> None:
    """Neither model's terminal states leak into the risk matrix."""
    for closed in ("approved", "resolved", "ignored", "archived"):
        assert is_open_status(closed) is False
