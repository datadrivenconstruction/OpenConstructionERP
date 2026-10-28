"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure schedule diff engine.

These tests exercise :func:`app.modules.schedule.diff_engine.diff_snapshots`
against hand-built normalized envelopes. The engine is pure (stdlib only), so
no database, fixtures, or async machinery are required.

Coverage:
* scope: activity added / removed -> correct change record + summary counts
* dates / duration: a finish slip surfaces finish_movement + dates/duration
  categories, and net finish movement tracks the project-finish shift
* logic: relationship retype + lag change + a brand-new link, with the
  ``logic`` category counted correctly
* cost as Decimal: 1000.10 == 1000.1 (no change), 1000.10 -> 1000.20 is a
  +0.10 cost change (never string concat, never float drift)
* multi-category: one activity carries both ``logic``-adjacent duration and
  date changes, each category counted once
* identical-vs-identical yields a fully zeroed diff
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.schedule.diff_engine import (
    CATEGORIES,
    DiffResult,
    diff_snapshots,
)


# ── Helpers ────────────────────────────────────────────────────────────────
def _activity(**overrides):
    """A fully-populated baseline activity; override individual fields."""
    base = {
        "id": "A1",
        "wbs_code": "1.1",
        "name": "Excavate foundation",
        "start_date": "2026-01-01",
        "end_date": "2026-01-10",
        "duration_days": 9,
        "progress_pct": "0",
        "status": "not_started",
        "early_start": "2026-01-01",
        "early_finish": "2026-01-10",
        "late_start": "2026-01-01",
        "late_finish": "2026-01-10",
        "total_float": 0,
        "free_float": 0,
        "is_critical": True,
        "actual_start": None,
        "actual_finish": None,
        "cost_planned": "1000.00",
        "cost_actual": "0.00",
        "constraint_type": None,
        "constraint_date": None,
        "parent_id": None,
    }
    base.update(overrides)
    return base


def _rel(predecessor_id, successor_id, relationship_type="FS", lag_days=0):
    return {
        "predecessor_id": predecessor_id,
        "successor_id": successor_id,
        "relationship_type": relationship_type,
        "lag_days": lag_days,
    }


def _env(activities=None, relationships=None, calendars=None, project_finish=None):
    env = {
        "activities": activities or [],
        "relationships": relationships or [],
        "calendars": calendars or {},
    }
    if project_finish is not None:
        env["project_finish"] = project_finish
    return env


def _find(changes, key):
    for c in changes:
        if c.key == key:
            return c
    return None


# ── Identical-vs-identical ─────────────────────────────────────────────────
def test_identical_snapshots_yield_no_changes():
    snap = _env(
        activities=[_activity()],
        relationships=[_rel("A1", "A2")],
        calendars={"std": {"working_days": ["mon", "tue", "wed", "thu", "fri"]}},
        project_finish="2026-01-10",
    )
    # Diff a snapshot against an independent but equal copy.
    other = _env(
        activities=[_activity()],
        relationships=[_rel("A1", "A2")],
        calendars={"std": {"working_days": ["mon", "tue", "wed", "thu", "fri"]}},
        project_finish="2026-01-10",
    )
    result = diff_snapshots(snap, other)

    assert isinstance(result, DiffResult)
    assert result.activities == []
    assert result.relationships == []
    assert result.calendars == []
    assert result.summary.net_finish_movement_days == 0
    assert result.summary.activities_added == 0
    assert result.summary.activities_removed == 0
    assert result.summary.activities_changed == 0
    assert result.summary.cost_planned_delta == Decimal("0")
    assert result.summary.cost_actual_delta == Decimal("0")
    # Every canonical category present and zero.
    assert set(result.summary.count_by_category) == set(CATEGORIES)
    assert all(v == 0 for v in result.summary.count_by_category.values())
    assert result.summary.largest_slips == []


# ── Scope: add / remove ────────────────────────────────────────────────────
def test_added_activity_is_scope_change():
    base = _env(activities=[_activity(id="A1")])
    target = _env(activities=[_activity(id="A1"), _activity(id="A2", wbs_code="1.2", name="Pour slab")])

    result = diff_snapshots(base, target)

    added = _find(result.activities, "A2")
    assert added is not None
    assert added.change_type == "added"
    assert added.categories == ["scope"]
    assert added.name == "Pour slab"
    assert result.summary.activities_added == 1
    assert result.summary.activities_removed == 0
    assert result.summary.count_by_category["scope"] == 1


def test_removed_activity_is_scope_change():
    base = _env(activities=[_activity(id="A1"), _activity(id="A2", wbs_code="1.2", name="Pour slab")])
    target = _env(activities=[_activity(id="A1")])

    result = diff_snapshots(base, target)

    removed = _find(result.activities, "A2")
    assert removed is not None
    assert removed.change_type == "removed"
    assert removed.categories == ["scope"]
    assert result.summary.activities_removed == 1
    assert result.summary.activities_added == 0
    assert result.summary.count_by_category["scope"] == 1


# ── Dates / duration: a finish slip ────────────────────────────────────────
def test_end_date_slip_surfaces_dates_and_finish_movement():
    base = _env(
        activities=[_activity(id="A1", end_date="2026-01-10")],
        project_finish="2026-01-10",
    )
    target = _env(
        activities=[_activity(id="A1", end_date="2026-01-15")],
        project_finish="2026-01-15",
    )

    result = diff_snapshots(base, target)

    change = _find(result.activities, "A1")
    assert change is not None
    assert change.change_type == "modified"
    # end_date is a "dates" field.
    assert "dates" in change.categories
    assert change.fields["end_date"]["from"] == "2026-01-10"
    assert change.fields["end_date"]["to"] == "2026-01-15"
    assert change.fields["end_date"]["categories"] == ["dates"]
    # Activity finish moved +5 days.
    assert change.finish_movement_days == 5
    # Net project finish moved +5 days.
    assert result.summary.net_finish_movement_days == 5
    # Largest-slips includes this activity.
    assert result.summary.largest_slips
    assert result.summary.largest_slips[0]["key"] == "A1"
    assert result.summary.largest_slips[0]["finish_movement_days"] == 5
    assert result.summary.count_by_category["dates"] == 1


def test_duration_and_float_changes_are_duration_category():
    base = _env(activities=[_activity(id="A1", duration_days=9, total_float=0)])
    target = _env(activities=[_activity(id="A1", duration_days=12, total_float=3)])

    result = diff_snapshots(base, target)
    change = _find(result.activities, "A1")
    assert change is not None
    assert change.categories == ["duration"]
    assert change.fields["duration_days"]["from"] == 9
    assert change.fields["duration_days"]["to"] == 12
    assert change.fields["total_float"]["from"] == 0
    assert change.fields["total_float"]["to"] == 3
    # One modified activity, duration counted once even though two fields changed.
    assert result.summary.count_by_category["duration"] == 1


def test_critical_path_flip_in_and_out():
    # in: became critical
    base = _env(activities=[_activity(id="A1", is_critical=False)])
    target = _env(activities=[_activity(id="A1", is_critical=True)])
    result = diff_snapshots(base, target)
    change = _find(result.activities, "A1")
    assert change.critical_path is True
    assert "duration" in change.categories
    assert result.summary.critical_path_in == 1
    assert result.summary.critical_path_out == 0

    # out: left the critical path
    base2 = _env(activities=[_activity(id="A1", is_critical=True)])
    target2 = _env(activities=[_activity(id="A1", is_critical=False)])
    result2 = diff_snapshots(base2, target2)
    change2 = _find(result2.activities, "A1")
    assert change2.critical_path is True
    assert result2.summary.critical_path_out == 1
    assert result2.summary.critical_path_in == 0


# ── Progress ───────────────────────────────────────────────────────────────
def test_progress_changes_are_progress_category():
    base = _env(activities=[_activity(id="A1", progress_pct="0", status="not_started")])
    target = _env(
        activities=[
            _activity(
                id="A1",
                progress_pct="50",
                status="in_progress",
                actual_start="2026-01-02",
            )
        ]
    )
    result = diff_snapshots(base, target)
    change = _find(result.activities, "A1")
    assert change.categories == ["progress"]
    assert change.fields["progress_pct"]["from"] == "50" or change.fields["progress_pct"]["to"] == "50"
    assert "status" in change.fields
    assert "actual_start" in change.fields
    assert result.summary.count_by_category["progress"] == 1


# ── Cost as Decimal ────────────────────────────────────────────────────────
def test_cost_decimal_equality_no_false_change():
    # 1000.10 vs 1000.1 must be equal -> no change record at all.
    base = _env(activities=[_activity(id="A1", cost_planned="1000.10")])
    target = _env(activities=[_activity(id="A1", cost_planned="1000.1")])

    result = diff_snapshots(base, target)
    assert _find(result.activities, "A1") is None
    assert result.summary.activities_changed == 0
    assert result.summary.count_by_category["cost"] == 0
    assert result.summary.cost_planned_delta == Decimal("0")


def test_cost_change_is_decimal_delta_not_string_concat():
    base = _env(activities=[_activity(id="A1", cost_planned="1000.10")])
    target = _env(activities=[_activity(id="A1", cost_planned="1000.20")])

    result = diff_snapshots(base, target)
    change = _find(result.activities, "A1")
    assert change is not None
    assert change.categories == ["cost"]
    # The delta is a true Decimal +0.10, never "1000.101000.20" or float noise.
    assert result.summary.cost_planned_delta == Decimal("0.10")
    assert isinstance(result.summary.cost_planned_delta, Decimal)
    assert result.summary.count_by_category["cost"] == 1


def test_cost_actual_delta_sums_across_activities():
    base = _env(
        activities=[
            _activity(id="A1", cost_actual="100.00"),
            _activity(id="A2", wbs_code="1.2", name="B", cost_actual="200.00"),
        ]
    )
    target = _env(
        activities=[
            _activity(id="A1", cost_actual="150.00"),
            _activity(id="A2", wbs_code="1.2", name="B", cost_actual="250.00"),
        ]
    )
    result = diff_snapshots(base, target)
    # +50 + +50 = +100
    assert result.summary.cost_actual_delta == Decimal("100.00")


# ── Logic: relationships ───────────────────────────────────────────────────
def test_relationship_retype_relag_and_add():
    base = _env(
        activities=[_activity(id="A1"), _activity(id="A2", wbs_code="1.2", name="B")],
        relationships=[_rel("A1", "A2", relationship_type="FS", lag_days=0)],
    )
    target = _env(
        activities=[
            _activity(id="A1"),
            _activity(id="A2", wbs_code="1.2", name="B"),
            _activity(id="A3", wbs_code="1.3", name="C"),
        ],
        relationships=[
            # FS -> SS retype AND lag 0 -> 2 on the same link
            _rel("A1", "A2", relationship_type="SS", lag_days=2),
            # a brand-new relationship
            _rel("A2", "A3", relationship_type="FS", lag_days=0),
        ],
    )

    result = diff_snapshots(base, target)

    # The retyped+relagged link.
    modified = _find(result.relationships, ("A1", "A2"))
    assert modified is not None
    assert modified.change_type == "retyped"  # retype dominates the label
    assert modified.fields["relationship_type"]["from"] == "FS"
    assert modified.fields["relationship_type"]["to"] == "SS"
    assert modified.fields["lag_days"]["from"] == 0
    assert modified.fields["lag_days"]["to"] == 2

    # The new link.
    added = _find(result.relationships, ("A2", "A3"))
    assert added is not None
    assert added.change_type == "added"

    # Counters: one retype, one relag, one add.
    assert result.summary.relationships_retyped == 1
    assert result.summary.relationships_relagged == 1
    assert result.summary.relationships_added == 1
    # logic counted once for the modified link + once for the added link = 2.
    assert result.summary.count_by_category["logic"] == 2


def test_relationship_removed_is_logic():
    base = _env(relationships=[_rel("A1", "A2")])
    target = _env(relationships=[])
    result = diff_snapshots(base, target)
    removed = _find(result.relationships, ("A1", "A2"))
    assert removed is not None
    assert removed.change_type == "removed"
    assert result.summary.relationships_removed == 1
    assert result.summary.count_by_category["logic"] == 1


# ── Multi-category on a single activity ────────────────────────────────────
def test_activity_carries_multiple_categories_each_counted_once():
    # One activity slips (dates) AND its duration grows (duration) AND it
    # picks up a cost change (cost). Three categories on one record, each
    # counted exactly once in the summary.
    base = _env(
        activities=[
            _activity(
                id="A1",
                end_date="2026-01-10",
                duration_days=9,
                cost_planned="1000.00",
            )
        ]
    )
    target = _env(
        activities=[
            _activity(
                id="A1",
                end_date="2026-01-13",
                duration_days=12,
                cost_planned="1200.00",
            )
        ]
    )

    result = diff_snapshots(base, target)
    change = _find(result.activities, "A1")
    assert change is not None
    assert set(change.categories) == {"dates", "duration", "cost"}
    # Each category incremented exactly once despite multiple fields.
    assert result.summary.count_by_category["dates"] == 1
    assert result.summary.count_by_category["duration"] == 1
    assert result.summary.count_by_category["cost"] == 1
    assert result.summary.activities_changed == 1
    assert change.finish_movement_days == 3
    assert result.summary.cost_planned_delta == Decimal("200.00")


# ── Constraint / calendar categories ───────────────────────────────────────
def test_constraint_change_is_constraint_category():
    base = _env(activities=[_activity(id="A1", constraint_type=None, constraint_date=None)])
    target = _env(activities=[_activity(id="A1", constraint_type="must_finish_on", constraint_date="2026-01-20")])
    result = diff_snapshots(base, target)
    change = _find(result.activities, "A1")
    assert change.categories == ["constraint"]
    assert result.summary.count_by_category["constraint"] == 1


def test_calendar_added_removed_changed():
    base = _env(
        calendars={
            "std": {"working_days": ["mon", "tue", "wed", "thu", "fri"]},
            "gone": {"working_days": ["mon"]},
        }
    )
    target = _env(
        calendars={
            "std": {"working_days": ["mon", "tue", "wed", "thu"]},  # changed
            "new": {"working_days": ["sat", "sun"]},  # added
        }
    )
    result = diff_snapshots(base, target)
    by_key = {(c.key, c.change_type) for c in result.calendars}
    assert ("gone", "removed") in by_key
    assert ("new", "added") in by_key
    assert ("std", "changed") in by_key
    # 3 calendar deltas.
    assert result.summary.count_by_category["calendar"] == 3


def test_calendar_reorder_is_not_a_change():
    # Working-day list reordered only -> signature equal -> no change.
    base = _env(calendars={"std": {"working_days": ["mon", "tue", "wed"]}})
    target = _env(calendars={"std": {"working_days": ["wed", "mon", "tue"]}})
    result = diff_snapshots(base, target)
    assert result.calendars == []
    assert result.summary.count_by_category["calendar"] == 0


# ── Fallback matching on (wbs_code, name) when id absent ────────────────────
def test_match_falls_back_to_wbs_and_name_when_id_absent():
    base = _env(activities=[{"wbs_code": "2.1", "name": "Frame walls", "end_date": "2026-02-01", "duration_days": 5}])
    target = _env(activities=[{"wbs_code": "2.1", "name": "Frame walls", "end_date": "2026-02-04", "duration_days": 8}])
    result = diff_snapshots(base, target)
    # Matched (not add+remove): exactly one modified record, no adds/removes.
    assert result.summary.activities_added == 0
    assert result.summary.activities_removed == 0
    assert result.summary.activities_changed == 1
    change = result.activities[0]
    assert change.change_type == "modified"
    assert change.finish_movement_days == 3


# ── Largest-slips ordering / top-10 cap ────────────────────────────────────
def test_largest_slips_sorted_by_absolute_movement_and_capped():
    acts_base = []
    acts_target = []
    # 12 activities each slipping by a different amount (1..12 days).
    for i in range(1, 13):
        aid = f"S{i}"
        acts_base.append(_activity(id=aid, wbs_code=f"9.{i}", name=f"Slip {i}", end_date="2026-03-01"))
        # slip by i days -> 2026-03-01 + i
        day = 1 + i
        acts_target.append(_activity(id=aid, wbs_code=f"9.{i}", name=f"Slip {i}", end_date=f"2026-03-{day:02d}"))
    result = diff_snapshots(_env(activities=acts_base), _env(activities=acts_target))
    slips = result.summary.largest_slips
    # Capped at 10.
    assert len(slips) == 10
    # Sorted descending by absolute movement -> first is the 12-day slip.
    assert slips[0]["finish_movement_days"] == 12
    assert slips[0]["key"] == "S12"
    # Monotonic non-increasing magnitude.
    mags = [abs(s["finish_movement_days"]) for s in slips]
    assert mags == sorted(mags, reverse=True)
