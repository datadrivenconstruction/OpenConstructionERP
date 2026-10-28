"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the meetings carry-over and minutes logic.

Scope:
    Pure, database-free helpers in ``app.modules.meetings.logic``: action
    status normalization, the overdue flag, action-item carry-over across a
    recurring series (own vs brought-forward), the series roll-up, the two
    validation gates, and the structured minutes-content builder. No database,
    ORM, or network is touched.
"""

from __future__ import annotations

import pytest

from app.modules.meetings.logic import (
    ACTION_STATUSES,
    action_is_live,
    action_is_overdue,
    annotate_action,
    build_minutes_content,
    minutes_issue_problems,
    normalize_action_status,
    split_actions_for_meeting,
    summarize_register,
    validate_action_fields,
)

REF = "2026-07-07"


def _action(
    *,
    id_: str,
    origin_id: str,
    origin_date: str,
    status: str = "open",
    due: str | None = None,
    desc: str = "Do the thing",
    owner: str | None = "Sam",
) -> dict:
    return {
        "id": id_,
        "origin_meeting_id": origin_id,
        "origin_meeting_number": "MTG-001",
        "origin_meeting_date": origin_date,
        "status": status,
        "due_date": due,
        "description": desc,
        "owner_name": owner,
        "owner_id": None,
    }


# ── Status + overdue ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("open", "open"),
        ("in_progress", "in_progress"),
        ("done", "done"),
        ("cancelled", "cancelled"),
        ("completed", "done"),  # legacy word maps onto the register status
        ("COMPLETED", "done"),
        ("nonsense", "open"),
        (None, "open"),
        ("", "open"),
    ],
)
def test_normalize_action_status(raw: str | None, expected: str) -> None:
    assert normalize_action_status(raw) == expected


def test_action_is_live() -> None:
    assert action_is_live("open") is True
    assert action_is_live("in_progress") is True
    assert action_is_live("done") is False
    assert action_is_live("cancelled") is False
    assert action_is_live("completed") is False  # maps to done


def test_action_is_overdue_only_for_live_past_due() -> None:
    assert action_is_overdue("2026-07-01", REF, "open") is True
    assert action_is_overdue("2026-07-01", REF, "in_progress") is True
    # Done / cancelled are never overdue even if the due date passed.
    assert action_is_overdue("2026-07-01", REF, "done") is False
    assert action_is_overdue("2026-07-01", REF, "cancelled") is False
    # Future due date is not overdue.
    assert action_is_overdue("2026-07-20", REF, "open") is False
    # Missing / unparseable dates never raise and are not overdue.
    assert action_is_overdue(None, REF, "open") is False
    assert action_is_overdue("not-a-date", REF, "open") is False


def test_action_is_overdue_grace_days() -> None:
    # Due yesterday, but a 3-day grace keeps it on track.
    assert action_is_overdue("2026-07-06", REF, "open", grace_days=3) is False
    # A 0-day grace makes it overdue.
    assert action_is_overdue("2026-07-06", REF, "open", grace_days=0) is True


def test_annotate_action_does_not_mutate_input() -> None:
    src = _action(id_="a1", origin_id="m1", origin_date="2026-07-01")
    out = annotate_action(src, REF)
    assert out["overdue"] is False  # no due date
    assert out["brought_forward"] is False
    assert "overdue" not in src  # original untouched


# ── Carry-over ───────────────────────────────────────────────────────────────


def test_split_actions_own_vs_brought_forward() -> None:
    # Series with three meetings; we are viewing the middle one (m2).
    actions = [
        _action(id_="a1", origin_id="m1", origin_date="2026-06-01", status="open", due="2026-06-15"),
        _action(id_="a2", origin_id="m1", origin_date="2026-06-01", status="done"),
        _action(id_="a3", origin_id="m2", origin_date="2026-06-15", status="open", due="2026-08-01"),
        _action(id_="a4", origin_id="m3", origin_date="2026-07-01", status="open"),
    ]
    own, brought = split_actions_for_meeting(actions, "m2", "2026-06-15", REF)

    # Own = raised in m2.
    assert [a["id"] for a in own] == ["a3"]
    # Brought forward = still-open action raised in an earlier meeting (a1).
    # a2 is done (closed -> not carried). a4 is from a later meeting (not carried back).
    assert [a["id"] for a in brought] == ["a1"]
    assert brought[0]["brought_forward"] is True
    assert brought[0]["overdue"] is True  # due 2026-06-15, ref 2026-07-07


def test_split_actions_closing_removes_from_carry_forward() -> None:
    actions = [
        _action(id_="a1", origin_id="m1", origin_date="2026-06-01", status="open", due="2026-06-15"),
    ]
    _own, brought = split_actions_for_meeting(actions, "m2", "2026-06-15", REF)
    assert [a["id"] for a in brought] == ["a1"]

    # Once the action is marked done it no longer carries forward for the series.
    actions[0]["status"] = "done"
    _own2, brought2 = split_actions_for_meeting(actions, "m2", "2026-06-15", REF)
    assert brought2 == []


def test_split_actions_same_day_origin_not_brought_forward() -> None:
    # An action raised in a meeting on the SAME date is not "earlier", so it is
    # not double-counted as brought forward into a sibling meeting.
    actions = [_action(id_="a1", origin_id="m1", origin_date="2026-06-15", status="open", due="2026-07-01")]
    own, brought = split_actions_for_meeting(actions, "m2", "2026-06-15", REF)
    assert own == []
    assert brought == []


def test_split_actions_one_off_meeting_has_no_carry_forward() -> None:
    actions = [_action(id_="a1", origin_id="m1", origin_date="2026-06-01", status="open", due="2026-07-01")]
    own, brought = split_actions_for_meeting(actions, "m1", "2026-06-01", REF)
    assert [a["id"] for a in own] == ["a1"]
    assert brought == []


def test_split_actions_sorted_by_due_date() -> None:
    actions = [
        _action(id_="late", origin_id="m1", origin_date="2026-06-01", due="2026-09-01"),
        _action(id_="soon", origin_id="m1", origin_date="2026-06-01", due="2026-07-10"),
        _action(id_="nodue", origin_id="m1", origin_date="2026-06-01", due=None),
    ]
    own, _brought = split_actions_for_meeting(actions, "m1", "2026-06-01", REF)
    assert [a["id"] for a in own] == ["soon", "late", "nodue"]


def test_summarize_register() -> None:
    actions = [
        _action(id_="a1", origin_id="m1", origin_date="2026-06-01", status="open", due="2026-06-15"),
        _action(id_="a2", origin_id="m1", origin_date="2026-06-01", status="in_progress", due="2026-08-01"),
        _action(id_="a3", origin_id="m1", origin_date="2026-06-01", status="done"),
        _action(id_="a4", origin_id="m1", origin_date="2026-06-01", status="cancelled"),
    ]
    summary = summarize_register(actions, REF)
    assert summary["total"] == 4
    assert summary["open"] == 1
    assert summary["in_progress"] == 1
    assert summary["done"] == 1
    assert summary["cancelled"] == 1
    assert summary["overdue"] == 1  # only a1 is live and past due


# ── Validation ───────────────────────────────────────────────────────────────


def test_validate_action_fields_requires_owner_and_due() -> None:
    assert validate_action_fields("owner-1", None, "2026-07-10", "open") == []
    assert validate_action_fields(None, "Sam", "2026-07-10", "open") == []

    problems = validate_action_fields(None, None, None, "open")
    assert any("owner" in p.lower() for p in problems)
    assert any("due date" in p.lower() for p in problems)


def test_validate_action_fields_rejects_non_iso_due() -> None:
    problems = validate_action_fields("o1", None, "next friday", "open")
    assert any("due date" in p.lower() for p in problems)


def test_validate_action_fields_status_in_known_set() -> None:
    # normalize maps completed -> done which is a known status, so no problem.
    assert validate_action_fields("o1", None, "2026-07-10", "completed") == []
    assert set(ACTION_STATUSES) == {"open", "in_progress", "done", "cancelled"}


def test_minutes_issue_problems_blocks_unaddressed_required_agenda() -> None:
    content = {
        "attendees_present": [{"name": "Sam"}],
        "agenda": [
            {"topic": "Safety", "required": True, "discussion": "", "decision": ""},
            {"topic": "Budget", "required": False, "discussion": "", "decision": ""},
        ],
    }
    problems = minutes_issue_problems(content)
    assert len(problems) == 1
    assert "Safety" in problems[0]


def test_minutes_issue_problems_allows_addressed_required_agenda() -> None:
    content = {
        "attendees_present": [{"name": "Sam"}],
        "agenda": [{"topic": "Safety", "required": True, "discussion": "Reviewed the JSA", "decision": ""}],
    }
    assert minutes_issue_problems(content) == []


def test_minutes_issue_problems_requires_someone_present() -> None:
    content = {"attendees_present": [], "agenda": []}
    problems = minutes_issue_problems(content)
    assert any("present" in p.lower() for p in problems)


# ── Minutes content builder ──────────────────────────────────────────────────


def _meeting() -> dict:
    return {
        "title": "Weekly Progress #3",
        "meeting_number": "MTG-003",
        "meeting_type": "progress",
        "meeting_date": "2026-07-07",
        "location": "Site office",
        "chairperson": "Alex Lead",
        "attendees": [
            {"name": "Sam", "company": "GC", "status": "present"},
            {"name": "Jo", "company": "Sub", "status": "absent"},
            {"name": "Kim", "company": "Client", "status": "present", "user_id": "u-kim"},
        ],
        "agenda_items": [
            {"number": "1", "topic": "Progress", "notes": "On track", "presenter": "Sam"},
            {"number": "2", "topic": "Safety", "discussion": "JSA reviewed", "decision": "Approved", "required": True},
        ],
        "minutes": "General notes line one\nline two",
        "metadata": {"decisions": [{"decision": "Adopt new hoarding layout"}, "Bare string decision"]},
    }


def test_build_minutes_content_present_absent_split() -> None:
    content = build_minutes_content(_meeting(), own_actions=[], brought_actions=[])
    present_names = {a["name"] for a in content["attendees_present"]}
    absent_names = {a["name"] for a in content["attendees_absent"]}
    assert present_names == {"Sam", "Kim"}
    assert absent_names == {"Jo"}


def test_build_minutes_content_checked_in_marks_present() -> None:
    # Jo is 'absent' on the roster but physically checked in -> counts present.
    content = build_minutes_content(_meeting(), [], [], checked_in_keys={"Jo"})
    present_names = {a["name"] for a in content["attendees_present"]}
    assert "Jo" in present_names
    assert all(a["name"] != "Jo" for a in content["attendees_absent"])


def test_build_minutes_content_agenda_discussion_and_decision() -> None:
    content = build_minutes_content(_meeting(), [], [])
    agenda = content["agenda"]
    assert agenda[0]["discussion"] == "On track"  # falls back to notes
    assert agenda[1]["discussion"] == "JSA reviewed"
    assert agenda[1]["decision"] == "Approved"
    assert agenda[1]["required"] is True
    # Decisions roll up agenda decisions + metadata decisions.
    assert "Approved" in content["decisions"]
    assert "Adopt new hoarding layout" in content["decisions"]
    assert "Bare string decision" in content["decisions"]


def test_build_minutes_content_actions_brought_forward_first() -> None:
    own = [{"description": "Own action", "owner_name": "Sam", "due_date": "2026-07-20", "status": "open"}]
    brought = [
        {
            "description": "Carried action",
            "owner_name": "Jo",
            "due_date": "2026-06-10",
            "status": "open",
            "brought_forward": True,
            "overdue": True,
            "origin_meeting_number": "MTG-002",
        }
    ]
    content = build_minutes_content(_meeting(), own, brought, next_meeting_date="2026-07-14")
    items = content["action_items"]
    # Brought-forward action leads.
    assert items[0]["description"] == "Carried action"
    assert items[0]["brought_forward"] is True
    assert items[0]["overdue"] is True
    assert items[1]["description"] == "Own action"
    assert content["next_meeting_date"] == "2026-07-14"
    assert content["summary"].startswith("General notes")


def test_build_minutes_content_is_json_safe_and_deterministic() -> None:
    import json

    a = build_minutes_content(_meeting(), [], [], generated_at="2026-07-07T00:00:00")
    b = build_minutes_content(_meeting(), [], [], generated_at="2026-07-07T00:00:00")
    assert a == b
    json.dumps(a)  # must not raise
