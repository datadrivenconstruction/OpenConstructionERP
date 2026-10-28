"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A bill of quantities has one state set, and everything that writes it agrees.

``BOQ.status`` is a free ``String(50)``, so nothing in the database constrains
it. The only constraint is ``BOQUpdate``'s pattern, and the only writers that
meet it are the ones going through the API. The seeders write the column
directly and so are never checked at all.

That is how the product came to ship a state it could not reach. The demo
seeder wrote ``"approved"``; the schema permits ``draft``, ``final`` and
``archived``; and the one act that approves a bill - ``POST /boqs/{id}/lock``
- records the approver in ``approved_by`` / ``approved_at`` and sets the
status to ``"final"``. So bills existed in a state with no transition into it
and no transition out of it, while ``archived``, which the schema permits and
``PATCH /boqs/{id}`` can reach, was written by nothing.

The two halves below have to be read together. One says the permitted set is
exactly ``draft | final | archived``; the other says every status literal
written anywhere in the application is in that set. Either alone is satisfied
by widening the pattern until the seeded data validates, which would enshrine
whatever the seeder happened to do as the specification.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_boq_status_set.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.boq.schemas import BOQUpdate

#: The lifecycle a bill of quantities has. ``draft`` is where every bill
#: starts, ``final`` is what approving one produces, ``archived`` retires it.
BOQ_STATUSES = ("draft", "final", "archived")

#: Rejected on purpose, each for its own reason. ``approved`` is what the
#: seeder used to write and is a fourth name for ``final``: approval and
#: finalisation are one act in this product. ``in_review`` is vocabulary that
#: exists only in a display label on the listing page and that nothing writes.
#: The rest are the ordinary near-misses a caller sends.
REJECTED_STATUSES = ("approved", "in_review", "locked", "Draft", "DRAFT", "", "deleted")

#: Surrounding whitespace is not a rejection: ``BOQUpdate`` sets
#: ``str_strip_whitespace``, so these arrive as the permitted value itself.
#: Recorded rather than left to be rediscovered, because "final " looks like
#: an eighth near-miss and is in fact the schema doing its job.
PADDED_STATUSES = (" final", "final ", "  draft  ")

APP_ROOT = Path(__file__).resolve().parents[3] / "app"


# ── The set itself ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", BOQ_STATUSES)
def test_the_permitted_states_are_accepted(status: str) -> None:
    assert BOQUpdate(status=status).status == status


@pytest.mark.parametrize("status", REJECTED_STATUSES)
def test_everything_outside_the_set_is_refused(status: str) -> None:
    """The negative half, without which a wide-open pattern passes everything.

    ``approved`` is named here deliberately. It is the value the demo data
    used to carry, so this assertion is the one that fails if someone widens
    the pattern to make that data validate instead of correcting the data.
    """
    with pytest.raises(ValidationError):
        BOQUpdate(status=status)


@pytest.mark.parametrize("status", PADDED_STATUSES)
def test_a_padded_status_is_stripped_rather_than_refused(status: str) -> None:
    """Whitespace around a permitted value is trimmed, not rejected."""
    assert BOQUpdate(status=status).status == status.strip()


# ── What the application actually writes ────────────────────────────────────


def _boq_status_literals(path: Path) -> list[tuple[int, str]]:
    """Every string literal passed as ``status=`` to a ``BOQ(...)`` constructor.

    Read from the syntax tree rather than by pattern-matching the text: the
    seeders build the row over several lines and a grep for ``status=`` in
    those files answers mostly about change orders, invoices and submissions,
    which have state sets of their own.
    """
    found: list[tuple[int, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "BOQ"):
            continue
        for kw in node.keywords:
            if kw.arg == "status" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                found.append((kw.value.lineno, kw.value.value))
    return found


def _files_constructing_boqs() -> list[Path]:
    """Application sources that build a ``BOQ`` row, found rather than listed.

    A hardcoded list of seeders would go stale the first time someone adds
    one, which is the failure mode this whole test exists to catch.
    """
    return sorted(p for p in APP_ROOT.rglob("*.py") if "BOQ(" in p.read_text(encoding="utf-8"))


def test_the_scan_finds_the_seeders_it_is_meant_to_check() -> None:
    """The denominator. An empty scan would make every assertion below vacuous."""
    writers = {path: literals for path in _files_constructing_boqs() if (literals := _boq_status_literals(path))}
    assert writers, "no BOQ constructor writes a status literal - the scan is looking in the wrong place"
    assert any(p.name == "demo_projects.py" for p in writers), (
        "the demo seeder is the writer this test was written for and the scan missed it"
    )


def test_every_seeded_status_is_one_the_api_can_reach() -> None:
    """A row seeded into a state no transition produces is a row nobody can move.

    The demo bills are what a new user sees first, so a status here that the
    API refuses is not a cosmetic mismatch: it is a bill whose state the
    product can display and cannot explain.
    """
    offenders: list[str] = []
    for path in _files_constructing_boqs():
        for lineno, status in _boq_status_literals(path):
            if status not in BOQ_STATUSES:
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{lineno} writes status={status!r}")
    assert not offenders, "seeded BOQ statuses outside the permitted set:\n  " + "\n  ".join(offenders)


def test_every_seeded_status_also_satisfies_the_update_schema() -> None:
    """The same claim asked of the schema instead of the tuple above.

    Two readers of one set, so the tuple in this file cannot drift away from
    the pattern in ``BOQUpdate`` without something failing.
    """
    for path in _files_constructing_boqs():
        for lineno, status in _boq_status_literals(path):
            assert BOQUpdate(status=status).status == status, (
                f"{path.relative_to(APP_ROOT.parent)}:{lineno} seeds a status the schema refuses"
            )


# ── What the transitions write ──────────────────────────────────────────────


def test_the_lock_and_unlock_transitions_write_permitted_states() -> None:
    """Locking a bill approves it, and the state it lands in must be in the set.

    ``lock_boq`` and ``unlock_boq`` are the only state transitions a BOQ has.
    They set the column through a compare-and-swap UPDATE rather than through
    ``BOQUpdate``, so nothing validates what they write either.
    """
    router = APP_ROOT / "modules" / "boq" / "router.py"
    tree = ast.parse(router.read_text(encoding="utf-8"), filename=str(router))

    written: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "values"):
            continue
        for kw in node.keywords:
            if kw.arg == "status" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                written.add(kw.value.value)

    assert written, "no BOQ status transition found in the router - the scan is looking in the wrong place"
    assert written <= set(BOQ_STATUSES), f"a transition writes a status outside the set: {sorted(written)}"
    assert "final" in written, (
        "locking a bill is the act that approves it and it must land in 'final'; "
        "if approval has become a state of its own, this test is the record that has to change with it"
    )
