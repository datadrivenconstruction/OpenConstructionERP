# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-function unit tests for the unified inbox merge/sort/scope logic.

These pin the DB-free helpers in ``app.modules.dashboard.inbox_logic`` that
drive the unified approvals/alerts inbox:

* ``severity_for_notification`` - the notification-type -> severity heuristic.
* ``scope_items_to_projects`` - the IDOR scope filter (admin = keep all;
  user-global alerts kept; out-of-scope project rows dropped).
* ``sort_inbox_items`` - deterministic newest-first + severity tiebreak.
* ``build_inbox`` - merge + scope + sort + cap, with correct pre-cap counts.

The module under test imports NOTHING from SQLAlchemy or ``app.database``, so
this file runs on any Python without a database (it does not use the ``session``
fixture or the embedded PostgreSQL cluster).

Run:
    cd backend
    python -m pytest tests/unit/test_dashboard_inbox_logic.py -v
"""

from __future__ import annotations

from typing import Any

from app.modules.dashboard.inbox_logic import (
    KIND_ALERT,
    KIND_APPROVAL,
    build_inbox,
    normalize_severity,
    scope_items_to_projects,
    severity_for_notification,
    sort_inbox_items,
)


def _item(**over: Any) -> dict[str, Any]:
    """A minimal inbox item dict with sensible defaults, overridable."""
    base: dict[str, Any] = {
        "id": "x:1",
        "kind": KIND_ALERT,
        "source": "notification",
        "title": "t",
        "project_id": None,
        "severity": "info",
        "created_at": None,
    }
    base.update(over)
    return base


# ── severity_for_notification ───────────────────────────────────────────────


class TestSeverityForNotification:
    def test_critical_hints_win(self) -> None:
        assert severity_for_notification("rfi.overdue") == "critical"
        assert severity_for_notification("approval.rejected") == "critical"
        assert severity_for_notification("job.failed") == "critical"

    def test_warning_hints(self) -> None:
        assert severity_for_notification("compliance.doc_expiring") == "warning"
        assert severity_for_notification("change_order.pending_approval") == "warning"
        assert severity_for_notification("rfi.review_requested") == "warning"

    def test_default_info(self) -> None:
        assert severity_for_notification("comment.added") == "info"
        assert severity_for_notification(None) == "info"
        assert severity_for_notification("") == "info"

    def test_critical_beats_warning_when_both_present(self) -> None:
        # "rejected" (critical) + "approval" (warning) in one type -> critical.
        assert severity_for_notification("approval.rejected.reminder") == "critical"

    def test_case_insensitive(self) -> None:
        assert severity_for_notification("RFI.OVERDUE") == "critical"


class TestNormalizeSeverity:
    def test_known_pass_through(self) -> None:
        assert normalize_severity("warning") == "warning"
        assert normalize_severity("CRITICAL") == "critical"

    def test_unknown_becomes_info(self) -> None:
        assert normalize_severity("bogus") == "info"
        assert normalize_severity(None) == "info"


# ── scope_items_to_projects (IDOR posture) ──────────────────────────────────


class TestScopeItemsToProjects:
    def test_admin_none_keeps_everything(self) -> None:
        items = [
            _item(id="a", project_id="p-out"),
            _item(id="b", project_id=None),
        ]
        out = scope_items_to_projects(items, None)
        assert {i["id"] for i in out} == {"a", "b"}

    def test_out_of_scope_project_dropped(self) -> None:
        items = [
            _item(id="in", project_id="p-in"),
            _item(id="out", project_id="p-out"),
        ]
        out = scope_items_to_projects(items, {"p-in"})
        assert [i["id"] for i in out] == ["in"]

    def test_user_global_alert_kept_when_scoped(self) -> None:
        # A notification with no project_id is the caller's own row and must
        # survive the scope filter even for a non-admin.
        items = [_item(id="global", project_id=None)]
        out = scope_items_to_projects(items, {"p-in"})
        assert [i["id"] for i in out] == ["global"]

    def test_empty_accessible_set_drops_all_project_rows(self) -> None:
        items = [
            _item(id="proj", project_id="p1"),
            _item(id="global", project_id=None),
        ]
        out = scope_items_to_projects(items, set())
        # Only the user-global row survives an empty (no-projects) scope.
        assert [i["id"] for i in out] == ["global"]

    def test_project_id_int_vs_str_coerced(self) -> None:
        # The set holds strings; an item whose project_id is non-str still
        # matches via str() coercion.
        items = [_item(id="x", project_id=123)]
        out = scope_items_to_projects(items, {"123"})
        assert [i["id"] for i in out] == ["x"]


# ── sort_inbox_items (deterministic ordering) ───────────────────────────────


class TestSortInboxItems:
    def test_newest_first(self) -> None:
        items = [
            _item(id="old", created_at="2026-01-01T00:00:00+00:00"),
            _item(id="new", created_at="2026-06-01T00:00:00+00:00"),
        ]
        out = sort_inbox_items(items)
        assert [i["id"] for i in out] == ["new", "old"]

    def test_missing_timestamp_sorts_after_timestamped(self) -> None:
        items = [
            _item(id="none", created_at=None),
            _item(id="dated", created_at="2026-06-01T00:00:00+00:00"),
        ]
        out = sort_inbox_items(items)
        # Empty-string created_at sorts last under reverse=True.
        assert [i["id"] for i in out] == ["dated", "none"]

    def test_severity_breaks_timestamp_tie(self) -> None:
        ts = "2026-06-01T00:00:00+00:00"
        items = [
            _item(id="info", created_at=ts, severity="info"),
            _item(id="crit", created_at=ts, severity="critical"),
            _item(id="warn", created_at=ts, severity="warning"),
        ]
        out = sort_inbox_items(items)
        assert [i["id"] for i in out] == ["crit", "warn", "info"]

    def test_fully_deterministic_on_id_tiebreak(self) -> None:
        ts = "2026-06-01T00:00:00+00:00"
        a = [_item(id="a", created_at=ts), _item(id="b", created_at=ts)]
        b = [_item(id="b", created_at=ts), _item(id="a", created_at=ts)]
        # Same inputs in any order produce the same output order.
        assert [i["id"] for i in sort_inbox_items(a)] == [i["id"] for i in sort_inbox_items(b)]

    def test_does_not_mutate_input(self) -> None:
        items = [
            _item(id="1", created_at="2026-01-01T00:00:00+00:00"),
            _item(id="2", created_at="2026-06-01T00:00:00+00:00"),
        ]
        original = [i["id"] for i in items]
        sort_inbox_items(items)
        assert [i["id"] for i in items] == original


# ── build_inbox (merge + scope + sort + cap) ────────────────────────────────


class TestBuildInbox:
    def test_merges_both_streams(self) -> None:
        approvals = [_item(id="ap1", kind=KIND_APPROVAL, project_id="p1", severity="warning")]
        alerts = [_item(id="al1", kind=KIND_ALERT, project_id=None)]
        result = build_inbox(approvals, alerts, accessible_project_ids={"p1"})
        ids = {i["id"] for i in result["items"]}
        assert ids == {"ap1", "al1"}
        assert result["total"] == 2
        assert result["approvals_count"] == 1
        assert result["alerts_count"] == 1

    def test_scoping_applied_to_counts(self) -> None:
        approvals = [
            _item(id="in", kind=KIND_APPROVAL, project_id="p1"),
            _item(id="out", kind=KIND_APPROVAL, project_id="p-other"),
        ]
        result = build_inbox(approvals, [], accessible_project_ids={"p1"})
        assert result["approvals_count"] == 1
        assert result["total"] == 1
        assert [i["id"] for i in result["items"]] == ["in"]

    def test_cap_limits_items_but_not_counts(self) -> None:
        approvals = [
            _item(
                id=f"a{i}",
                kind=KIND_APPROVAL,
                project_id="p1",
                created_at=f"2026-06-{i + 1:02d}T00:00:00+00:00",
            )
            for i in range(5)
        ]
        result = build_inbox(approvals, [], accessible_project_ids={"p1"}, limit=2)
        assert len(result["items"]) == 2
        # Counts reflect the full scoped total, not the cap.
        assert result["approvals_count"] == 5
        assert result["total"] == 5
        # The two returned are the newest two (a4, a3).
        assert [i["id"] for i in result["items"]] == ["a4", "a3"]

    def test_admin_scope_keeps_out_of_set_rows(self) -> None:
        alerts = [_item(id="any", kind=KIND_ALERT, project_id="p-anything")]
        result = build_inbox([], alerts, accessible_project_ids=None)
        assert result["alerts_count"] == 1
        assert [i["id"] for i in result["items"]] == ["any"]

    def test_empty_inputs(self) -> None:
        result = build_inbox([], [], accessible_project_ids=set())
        assert result == {
            "items": [],
            "total": 0,
            "approvals_count": 0,
            "alerts_count": 0,
        }

    def test_zero_limit_returns_no_items_but_real_counts(self) -> None:
        alerts = [_item(id="al1", project_id=None)]
        result = build_inbox([], alerts, accessible_project_ids=set(), limit=0)
        assert result["items"] == []
        assert result["alerts_count"] == 1

    def test_ordering_across_streams(self) -> None:
        approvals = [
            _item(
                id="ap_old",
                kind=KIND_APPROVAL,
                project_id="p1",
                created_at="2026-01-01T00:00:00+00:00",
            )
        ]
        alerts = [
            _item(
                id="al_new",
                kind=KIND_ALERT,
                project_id=None,
                created_at="2026-06-01T00:00:00+00:00",
            )
        ]
        result = build_inbox(approvals, alerts, accessible_project_ids={"p1"})
        assert [i["id"] for i in result["items"]] == ["al_new", "ap_old"]
