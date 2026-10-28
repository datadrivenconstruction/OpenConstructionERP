# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The dates on a demo RFI have to agree with the labels the register prints.

On the RFI screen a row printed "22d" in the DAYS column and a red "+113" pill
beside it, meaning it was raised 22 days ago and is 113 days past its deadline:
a deadline 91 days before the request existed. The cause was two clocks. The
seeder dated ``response_due_date`` and ``responded_at`` off the project's story
start, a fixed calendar date, while ``created_at`` fell through to the column
default, which is the moment the demo was installed. The answered half of the
register read a response time of 0d for the same reason, the response sitting
months before the row was created and the router clamping a negative span.

The numbers here come from ``_compute_rfi_fields``, the router function that
produced those two, rather than from a copy of its arithmetic in the test. Both
sides of the seeder's ``_RFIS.get(demo_id) or generated`` choice are covered:
the curated status lists are read out of the source, and the generated demos
alternate answered and open, which is a shape no curated list has.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.demo_projects import _rfi_schedule
from app.modules.rfi.router import _compute_rfi_fields

# Read from the checkout rather than from demo_projects.__file__, so the lists
# under test are the ones this commit ships whatever the install layout is.
_SOURCE = Path(__file__).resolve().parents[2] / "app" / "core" / "demo_projects.py"

# The seeder's own project start. Kept as a literal here on purpose: if that
# date is ever moved, these checks should still run against a fixed anchor and
# the ``now`` values below are what varies.
_BASE = datetime(2026, 4, 1)

# Clocks to date the same rows against. The realistic case is a demo installed
# months after the story starts; the first two are a demo installed the day it
# starts and days after, where the offsets have almost no room to spread and
# the guards in the helper are what keep the dates in order.
_NOWS = [_BASE, _BASE + timedelta(days=3), _BASE + timedelta(days=123), _BASE + timedelta(days=800)]


def _curated_status_lists() -> list[tuple[str, list[str]]]:
    """Statuses of each hand-authored demo's RFIs, in the order they are seeded.

    ``_RFIS`` is a local of ``_seed_module_data`` and needs a database to reach
    any other way, so it is read from the syntax tree. Its values are plain
    literals, which is why this one can be evaluated rather than walked.
    """
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if "_RFIS" not in names or node.value is None:
            continue
        demos = ast.literal_eval(node.value)
        return [(demo_id, [r["status"] for r in rows]) for demo_id, rows in demos.items()]
    raise AssertionError(f"cannot find the _RFIS demo lists in {_SOURCE}")


def _generated_status_lists() -> list[tuple[str, list[str]]]:
    """The alternating shape ``_generate_module_data`` emits, 6 to 8 RFIs.

    Every demo outside the five hand-authored ones takes this branch, and it
    interleaves the two statuses evenly, which none of the curated lists do.
    """
    return [(f"generated-{n}", ["answered" if i % 2 == 0 else "open" for i in range(n)]) for n in (6, 7, 8)]


_STATUS_LISTS = _curated_status_lists() + _generated_status_lists()


def _seeded_rows(statuses: list[str], now: datetime) -> list[SimpleNamespace]:
    """Date a demo's RFIs the way the seeder does, counting within each status."""
    answered_seen = 0
    open_seen = 0
    rows = []
    for status in statuses:
        answered = status == "answered"
        if answered:
            ordinal = answered_seen
            answered_seen += 1
        else:
            ordinal = open_seen
            open_seen += 1
        created_at, due_date, required_date, responded_at = _rfi_schedule(
            answered=answered, ordinal=ordinal, base=_BASE, now=now
        )
        rows.append(
            SimpleNamespace(
                status=status,
                created_at=created_at,
                responded_at=responded_at,
                response_due_date=due_date,
                date_required=required_date,
            )
        )
    return rows


@pytest.mark.parametrize("now", _NOWS, ids=lambda n: f"day{(n - _BASE).days}")
@pytest.mark.parametrize(("demo_id", "statuses"), _STATUS_LISTS, ids=lambda v: v if isinstance(v, str) else "")
def test_a_reply_is_never_due_before_the_question_was_asked(demo_id: str, statuses: list[str], now: datetime) -> None:
    """The contradiction the screen showed, stated as the seeder's invariant."""
    for row in _seeded_rows(statuses, now):
        raised = row.created_at.date()
        due = datetime.fromisoformat(row.response_due_date).date()
        required = datetime.fromisoformat(row.date_required).date()
        assert due > raised, f"{demo_id}: a reply was due {(raised - due).days}d before the RFI was raised"
        assert required > raised, f"{demo_id}: the answer was needed on site before the RFI was raised"


@pytest.mark.parametrize("now", _NOWS, ids=lambda n: f"day{(n - _BASE).days}")
@pytest.mark.parametrize(("demo_id", "statuses"), _STATUS_LISTS, ids=lambda v: v if isinstance(v, str) else "")
def test_an_answered_rfi_took_some_days_to_answer(demo_id: str, statuses: list[str], now: datetime) -> None:
    """The register reported a response time of zero for its whole answered half.

    ``days_open`` is what the DAYS column binds to, and for an answered row the
    router measures it to ``responded_at`` rather than to now, so a response
    dated before the row was created collapsed to 0.
    """
    answered = [row for row in _seeded_rows(statuses, now) if row.status == "answered"]
    assert answered, f"{demo_id} seeds no answered RFI, so this check would pass on nothing"
    for row in answered:
        _, days_open = _compute_rfi_fields(row)
        assert days_open >= 1, f"{demo_id}: an answered RFI reports {days_open}d to answer"


@pytest.mark.parametrize("now", _NOWS, ids=lambda n: f"day{(n - _BASE).days}")
@pytest.mark.parametrize(("demo_id", "statuses"), _STATUS_LISTS, ids=lambda v: v if isinstance(v, str) else "")
def test_no_rfi_predates_the_project_it_belongs_to(demo_id: str, statuses: list[str], now: datetime) -> None:
    """Placing the open rows near today must not push them behind the start."""
    for row in _seeded_rows(statuses, now):
        assert row.created_at >= _BASE.replace(tzinfo=UTC), f"{demo_id}: an RFI was raised before the project started"


@pytest.mark.parametrize(("demo_id", "statuses"), _STATUS_LISTS, ids=lambda v: v if isinstance(v, str) else "")
def test_the_open_rows_are_not_one_wall_of_overdue(demo_id: str, statuses: list[str]) -> None:
    """Every open RFI in the demo was overdue, and by the same 113 days.

    Dated against the real clock, because ``is_overdue`` is measured against
    the real one inside the router: rows built for a simulated today would all
    fall behind a deadline as the calendar moved on, and this check would rot
    into a failure that says nothing about the seeder. One row past its
    deadline is wanted, so the overdue pill has something honest to sit on.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = [row for row in _seeded_rows(statuses, now) if row.status == "open"]
    assert rows, f"{demo_id} seeds no open RFI, so this check would pass on nothing"
    overdue = [row for row in rows if _compute_rfi_fields(row)[0]]
    assert overdue, f"{demo_id}: no open RFI is late, so the overdue pill never shows"
    assert len(overdue) < len(rows) or len(rows) == 1, f"{demo_id}: all {len(rows)} open RFIs are past their deadline"
    for row in overdue:
        days_late = (now.date() - datetime.fromisoformat(row.response_due_date).date()).days
        assert days_late < 30, f"{demo_id}: an open RFI is {days_late} days past its deadline"


@pytest.mark.parametrize(("demo_id", "statuses"), _STATUS_LISTS, ids=lambda v: v if isinstance(v, str) else "")
def test_the_deadlines_are_spread_rather_than_stacked_on_one_day(demo_id: str, statuses: list[str]) -> None:
    """All eight deadlines used to be the same date, which is how they read."""
    rows = _seeded_rows(statuses, _BASE + timedelta(days=123))
    if len(rows) < 2:
        pytest.skip("a single RFI cannot be spread")
    assert len({row.response_due_date for row in rows}) > 1, f"{demo_id}: one deadline for every RFI"


def test_the_dates_the_seeder_used_before_produce_the_reported_numbers() -> None:
    """Ties the two shapes together, so neither half is read as always true.

    The old row dated ``created_at`` from the install and everything else from
    the project start. Under it an answered RFI reports 0 days to answer and an
    open one is months past a deadline it was given before it was raised.
    """
    now = _BASE + timedelta(days=123)
    old_answered = SimpleNamespace(
        status="answered",
        created_at=now.replace(tzinfo=UTC),
        responded_at=(_BASE + timedelta(days=5)).strftime("%Y-%m-%d"),
        response_due_date=(_BASE + timedelta(days=10)).strftime("%Y-%m-%d"),
    )
    old_open = SimpleNamespace(
        status="open",
        created_at=now.replace(tzinfo=UTC),
        responded_at=None,
        response_due_date=(_BASE + timedelta(days=10)).strftime("%Y-%m-%d"),
    )
    assert _compute_rfi_fields(old_answered)[1] == 0
    assert _compute_rfi_fields(old_open)[0] is True

    new_answered = _seeded_rows(["answered"], now)[0]
    assert _compute_rfi_fields(new_answered)[1] >= 1
