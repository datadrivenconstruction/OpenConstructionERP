"""Unit tests for stats endpoints and computed fields across RFI, Safety, Tasks, Schedule.

Tests cover:
- RFI: is_overdue, days_open computed fields, RFIStatsResponse schema
- Safety: SafetyStatsResponse, SafetyTrendsResponse schemas, risk tier computation
- Tasks: is_overdue computed field, TaskStatsResponse schema
- Schedule: ScheduleStatsResponse schema
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.rfi.schemas import RFIResponse, RFIStatsResponse
from app.modules.safety.schemas import (
    SafetyStatsResponse,
    SafetyTrendEntry,
    SafetyTrendsResponse,
)
from app.modules.safety.service import _compute_risk_tier
from app.modules.schedule.schemas import ScheduleStatsResponse
from app.modules.tasks.schemas import TaskResponse, TaskStatsResponse

# ── RFI computed fields ─────────────────────────────────────────────────────


class TestRFIComputedFields:
    """Tests for is_overdue and days_open on RFIResponse."""

    def test_rfi_response_has_is_overdue_field(self) -> None:
        assert "is_overdue" in RFIResponse.model_fields

    def test_rfi_response_has_days_open_field(self) -> None:
        assert "days_open" in RFIResponse.model_fields

    def test_is_overdue_defaults_to_false(self) -> None:
        rfi = RFIResponse(
            id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222",
            rfi_number="RFI-001",
            subject="Test",
            question="Test question",
            raised_by="33333333-3333-3333-3333-333333333333",
            status="open",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert rfi.is_overdue is False

    def test_days_open_defaults_to_zero(self) -> None:
        rfi = RFIResponse(
            id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222",
            rfi_number="RFI-001",
            subject="Test",
            question="Test question",
            raised_by="33333333-3333-3333-3333-333333333333",
            status="open",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert rfi.days_open == 0


class TestRFIStatsSchema:
    """Tests for RFIStatsResponse schema."""

    def test_stats_default_values(self) -> None:
        stats = RFIStatsResponse()
        assert stats.total == 0
        assert stats.open == 0
        assert stats.overdue == 0
        assert stats.avg_days_to_response is None
        assert stats.by_status == {}
        assert stats.cost_impact_count == 0
        assert stats.schedule_impact_count == 0

    def test_stats_with_values(self) -> None:
        stats = RFIStatsResponse(
            total=10,
            by_status={"open": 3, "closed": 7},
            open=3,
            overdue=1,
            avg_days_to_response=5.5,
            cost_impact_count=2,
            schedule_impact_count=1,
        )
        assert stats.total == 10
        assert stats.open == 3
        assert stats.overdue == 1
        assert stats.avg_days_to_response == 5.5


# ── Safety stats & trends schemas ──────────────────────────────────────────


class TestSafetyStatsSchema:
    """Tests for SafetyStatsResponse schema."""

    def test_stats_default_values(self) -> None:
        stats = SafetyStatsResponse()
        assert stats.total_incidents == 0
        assert stats.total_observations == 0
        assert stats.days_without_incident is None
        assert stats.total_days_lost == 0
        assert stats.recordable_incidents == 0
        assert stats.ltifr is None
        assert stats.trir is None
        assert stats.incidents_by_type == {}
        assert stats.incidents_by_status == {}
        assert stats.observations_by_risk_tier == {}
        assert stats.open_corrective_actions == 0

    def test_stats_with_values(self) -> None:
        stats = SafetyStatsResponse(
            total_incidents=5,
            total_observations=20,
            days_without_incident=15,
            total_days_lost=8,
            recordable_incidents=2,
            incidents_by_type={"injury": 3, "near_miss": 2},
            incidents_by_status={"reported": 1, "closed": 4},
            observations_by_risk_tier={"low": 10, "medium": 6, "high": 3, "critical": 1},
            open_corrective_actions=3,
        )
        assert stats.total_incidents == 5
        assert stats.days_without_incident == 15
        assert stats.observations_by_risk_tier["critical"] == 1


class TestSafetyTrendsSchema:
    """Tests for SafetyTrendsResponse schema."""

    def test_trends_default_values(self) -> None:
        trends = SafetyTrendsResponse(period_type="monthly")
        assert trends.period_type == "monthly"
        assert trends.entries == []

    def test_trends_with_entries(self) -> None:
        entries = [
            SafetyTrendEntry(period="2026-01", incident_count=2, observation_count=5, days_lost=3),
            SafetyTrendEntry(period="2026-02", incident_count=1, observation_count=8, days_lost=0),
        ]
        trends = SafetyTrendsResponse(period_type="monthly", entries=entries)
        assert len(trends.entries) == 2
        assert trends.entries[0].period == "2026-01"
        assert trends.entries[0].incident_count == 2
        assert trends.entries[1].days_lost == 0


class TestRiskTierComputation:
    """Tests for _compute_risk_tier helper."""

    @pytest.mark.parametrize(
        ("score", "expected_tier"),
        [
            (1, "low"),
            (5, "low"),
            (6, "medium"),
            (10, "medium"),
            (11, "high"),
            (15, "high"),
            (16, "critical"),
            (25, "critical"),
        ],
    )
    def test_risk_tier_boundaries(self, score: int, expected_tier: str) -> None:
        assert _compute_risk_tier(score) == expected_tier


# ── Tasks computed fields ──────────────────────────────────────────────────


class TestTaskComputedFields:
    """Tests for is_overdue on TaskResponse."""

    def test_task_response_has_is_overdue_field(self) -> None:
        assert "is_overdue" in TaskResponse.model_fields

    def test_is_overdue_defaults_to_false(self) -> None:
        task = TaskResponse(
            id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222",
            task_type="task",
            title="Test task",
            status="open",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert task.is_overdue is False


class TestTaskStatsSchema:
    """Tests for TaskStatsResponse schema."""

    def test_stats_default_values(self) -> None:
        stats = TaskStatsResponse()
        assert stats.total == 0
        assert stats.by_status == {}
        assert stats.by_type == {}
        assert stats.by_priority == {}
        assert stats.overdue_count == 0
        assert stats.completed_count == 0
        assert stats.avg_checklist_progress is None

    def test_stats_with_values(self) -> None:
        stats = TaskStatsResponse(
            total=15,
            by_status={"open": 5, "in_progress": 7, "completed": 3},
            by_type={"task": 10, "decision": 5},
            by_priority={"normal": 10, "high": 3, "urgent": 2},
            overdue_count=2,
            completed_count=3,
            avg_checklist_progress=45.5,
        )
        assert stats.total == 15
        assert stats.overdue_count == 2
        assert stats.avg_checklist_progress == 45.5


# ── Schedule stats schema ──────────────────────────────────────────────────


class TestScheduleStatsSchema:
    """Tests for ScheduleStatsResponse schema."""

    def test_stats_default_values(self) -> None:
        stats = ScheduleStatsResponse()
        assert stats.total_activities == 0
        assert stats.critical_count == 0
        assert stats.on_track == 0
        assert stats.delayed == 0
        assert stats.completed == 0
        assert stats.not_started == 0
        assert stats.in_progress == 0
        assert stats.progress_pct == 0.0
        assert stats.total_duration_days == 0

    def test_stats_with_values(self) -> None:
        stats = ScheduleStatsResponse(
            total_activities=50,
            critical_count=8,
            on_track=30,
            delayed=5,
            completed=10,
            not_started=15,
            in_progress=20,
            progress_pct=35.5,
            total_duration_days=450,
        )
        assert stats.total_activities == 50
        assert stats.critical_count == 8
        assert stats.progress_pct == 35.5


# ── RFI router helper tests ────────────────────────────────────────────────


class TestRFIRouterHelpers:
    """Tests for _compute_rfi_fields helper in router."""

    def test_overdue_when_past_due_and_open(self) -> None:
        from app.modules.rfi.router import _compute_rfi_fields

        class MockRFI:
            created_at = datetime.now(UTC) - timedelta(days=20)
            status = "open"
            response_due_date = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%d")
            responded_at = None

        is_overdue, days_open = _compute_rfi_fields(MockRFI())
        assert is_overdue is True
        assert days_open >= 19  # At least 19 days open

    def test_not_overdue_when_closed(self) -> None:
        from app.modules.rfi.router import _compute_rfi_fields

        class MockRFI:
            created_at = datetime.now(UTC) - timedelta(days=30)
            status = "closed"
            response_due_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d")
            responded_at = (datetime.now(UTC) - timedelta(days=15)).strftime("%Y-%m-%d")

        is_overdue, days_open = _compute_rfi_fields(MockRFI())
        assert is_overdue is False
        assert 14 <= days_open <= 16  # Closed after ~15 days

    def test_not_overdue_when_no_due_date(self) -> None:
        from app.modules.rfi.router import _compute_rfi_fields

        class MockRFI:
            created_at = datetime.now(UTC) - timedelta(days=5)
            status = "open"
            response_due_date = None
            responded_at = None

        is_overdue, days_open = _compute_rfi_fields(MockRFI())
        assert is_overdue is False
        assert days_open >= 4

    def test_not_overdue_when_future_due_date(self) -> None:
        from app.modules.rfi.router import _compute_rfi_fields

        class MockRFI:
            created_at = datetime.now(UTC) - timedelta(days=3)
            status = "open"
            response_due_date = (datetime.now(UTC) + timedelta(days=10)).strftime("%Y-%m-%d")
            responded_at = None

        is_overdue, days_open = _compute_rfi_fields(MockRFI())
        assert is_overdue is False


# ── Task router helper tests ───────────────────────────────────────────────


class TestTaskRouterHelpers:
    """Tests for _compute_is_overdue helper in router."""

    def test_overdue_when_past_due_and_not_completed(self) -> None:
        from app.modules.tasks.router import _compute_is_overdue

        class MockTask:
            status = "open"
            due_date = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d")

        assert _compute_is_overdue(MockTask()) is True

    def test_not_overdue_when_completed(self) -> None:
        from app.modules.tasks.router import _compute_is_overdue

        class MockTask:
            status = "completed"
            due_date = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d")

        assert _compute_is_overdue(MockTask()) is False

    def test_not_overdue_when_no_due_date(self) -> None:
        from app.modules.tasks.router import _compute_is_overdue

        class MockTask:
            status = "open"
            due_date = None

        assert _compute_is_overdue(MockTask()) is False

    def test_not_overdue_when_future_due_date(self) -> None:
        from app.modules.tasks.router import _compute_is_overdue

        class MockTask:
            status = "in_progress"
            due_date = (datetime.now(UTC) + timedelta(days=5)).strftime("%Y-%m-%d")

        assert _compute_is_overdue(MockTask()) is False
