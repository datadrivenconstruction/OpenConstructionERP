"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the schedule diff envelope adapters (snapshot_envelope).

Pure (stdlib only). Exercises ``live_envelope`` / ``normalize_envelope`` and a
round-trip through the real ``diff_snapshots`` so the adapter and engine are
proven to line up without the app / DB barrier.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.modules.schedule.diff_engine import diff_snapshots
from app.modules.schedule.snapshot_envelope import (
    live_envelope,
    normalize_envelope,
)


def _activity(**kw) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "wbs_code": "1.1",
        "name": "Task",
        "parent_id": None,
        "start_date": "2026-01-01",
        "end_date": "2026-01-10",
        "duration_days": 9,
        "is_critical": True,
        "progress_pct": "0",
        "status": "not_started",
        "cost_planned": Decimal("1000.10"),
        "cost_actual": None,
        "constraint_type": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _rel(pred, succ, rtype="FS", lag=0) -> SimpleNamespace:
    return SimpleNamespace(predecessor_id=pred, successor_id=succ, relationship_type=rtype, lag_days=lag)


def test_live_envelope_shape_and_scalar_coercion() -> None:
    a = _activity()
    env = live_envelope([a], [])

    assert set(env) >= {"activities", "relationships", "calendars"}
    assert env["project_finish"] == "2026-01-10"
    row = env["activities"][0]
    # UUID + Decimal are stringified; None fields dropped; ints kept.
    assert row["id"] == str(a.id)
    assert row["cost_planned"] == "1000.10"
    assert row["duration_days"] == 9
    assert "cost_actual" not in row  # None dropped
    assert "parent_id" not in row


def test_relationship_row_defaults() -> None:
    p, s = uuid.uuid4(), uuid.uuid4()
    env = live_envelope([_activity(id=p), _activity(id=s)], [_rel(p, s, "SS", 3)])
    rel = env["relationships"][0]
    assert rel["predecessor_id"] == str(p)
    assert rel["successor_id"] == str(s)
    assert rel["relationship_type"] == "SS"
    assert rel["lag_days"] == 3


def test_normalize_canonical_passthrough() -> None:
    raw = {"activities": [{"id": "A"}], "relationships": [{"predecessor_id": "A", "successor_id": "B"}]}
    env = normalize_envelope(raw)
    assert env["activities"] == [{"id": "A"}]
    assert env["relationships"] == [{"predecessor_id": "A", "successor_id": "B"}]
    assert env["calendars"] == {}


def test_normalize_bare_list() -> None:
    env = normalize_envelope([{"id": "A"}, {"id": "B"}])
    assert len(env["activities"]) == 2
    assert env["relationships"] == []


def test_normalize_tasks_links_aliases() -> None:
    env = normalize_envelope({"tasks": [{"id": "A"}], "links": [{"predecessor_id": "A", "successor_id": "B"}]})
    assert env["activities"] == [{"id": "A"}]
    assert env["relationships"] == [{"predecessor_id": "A", "successor_id": "B"}]


def test_normalize_id_keyed_dict() -> None:
    env = normalize_envelope({"A": {"id": "A", "name": "x"}, "B": {"id": "B", "name": "y"}})
    assert {a["id"] for a in env["activities"]} == {"A", "B"}


def test_normalize_none_and_garbage() -> None:
    assert normalize_envelope(None)["activities"] == []
    assert normalize_envelope(42)["activities"] == []


def test_round_trip_diff_detects_slip_add_and_logic() -> None:
    a1 = _activity(id="A", end_date="2026-01-10", duration_days=9)
    a2 = _activity(id="B", end_date="2026-01-15", duration_days=4)
    base = live_envelope([a1, a2], [_rel("A", "B", "FS", 0)])

    # B finishes 5 days later; add C; retype the A->B link to SS.
    a2_slipped = _activity(id="B", end_date="2026-01-20", duration_days=9)
    a3 = _activity(id="C", end_date="2026-01-25")
    target = live_envelope([a1, a2_slipped, a3], [_rel("A", "B", "SS", 0)])

    result = diff_snapshots(base, target)
    assert result.summary.activities_added == 1
    assert result.summary.activities_changed >= 1
    assert result.summary.relationships_retyped == 1
    # The B slip is reported with a positive finish movement.
    b_change = next(c for c in result.activities if c.key.endswith("B"))
    assert b_change.finish_movement_days > 0
