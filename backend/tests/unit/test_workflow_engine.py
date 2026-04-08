"""Tests for the workflow engine — ball-in-court tracking, step navigation, due dates."""

import pytest

from app.core.workflow_engine import (
    NCR_WORKFLOW,
    RFI_WORKFLOW,
    SUBMITTAL_WORKFLOW,
    TRANSMITTAL_WORKFLOW,
    WorkflowEngine,
    WorkflowStep,
)

# ── WorkflowStep construction ────────────────────────────────────────────


class TestWorkflowStep:
    def test_defaults(self) -> None:
        step = WorkflowStep(name="draft", role="author")
        assert step.name == "draft"
        assert step.role == "author"
        assert step.auto_advance is False
        assert step.timeout_days is None

    def test_custom_fields(self) -> None:
        step = WorkflowStep(name="review", role="reviewer", auto_advance=True, timeout_days=7)
        assert step.auto_advance is True
        assert step.timeout_days == 7

    def test_frozen(self) -> None:
        step = WorkflowStep(name="draft", role="author")
        with pytest.raises(AttributeError):
            step.name = "other"  # type: ignore[misc]


# ── WorkflowEngine basics ────────────────────────────────────────────────


class TestWorkflowEngine:
    @pytest.fixture
    def engine(self) -> WorkflowEngine:
        return WorkflowEngine(
            steps=[
                WorkflowStep(name="draft", role="author"),
                WorkflowStep(name="review", role="reviewer", timeout_days=7),
                WorkflowStep(name="approve", role="approver"),
            ]
        )

    def test_creation_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one step"):
            WorkflowEngine(steps=[])

    def test_creation_duplicate_raises(self) -> None:
        with pytest.raises(ValueError, match="Duplicate step name"):
            WorkflowEngine(
                steps=[
                    WorkflowStep(name="a", role="x"),
                    WorkflowStep(name="a", role="y"),
                ]
            )

    def test_len(self, engine: WorkflowEngine) -> None:
        assert len(engine) == 3

    def test_repr(self, engine: WorkflowEngine) -> None:
        assert "draft → review → approve" in repr(engine)

    # ── advance / retreat ─────────────────────────────────────────────────

    def test_advance_returns_next(self, engine: WorkflowEngine) -> None:
        assert engine.advance("draft") == "review"
        assert engine.advance("review") == "approve"

    def test_advance_returns_none_at_final(self, engine: WorkflowEngine) -> None:
        assert engine.advance("approve") is None

    def test_retreat_returns_previous(self, engine: WorkflowEngine) -> None:
        assert engine.retreat("approve") == "review"
        assert engine.retreat("review") == "draft"

    def test_retreat_returns_none_at_first(self, engine: WorkflowEngine) -> None:
        assert engine.retreat("draft") is None

    def test_advance_unknown_step_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(KeyError, match="Unknown workflow step"):
            engine.advance("nonexistent")

    def test_retreat_unknown_step_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(KeyError, match="Unknown workflow step"):
            engine.retreat("nonexistent")

    # ── ball_in_court ─────────────────────────────────────────────────────

    def test_ball_in_court(self, engine: WorkflowEngine) -> None:
        assert engine.ball_in_court("draft") == "author"
        assert engine.ball_in_court("review") == "reviewer"
        assert engine.ball_in_court("approve") == "approver"

    def test_ball_in_court_unknown_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(KeyError):
            engine.ball_in_court("missing")

    # ── calculate_due_date ────────────────────────────────────────────────

    def test_due_date_with_timeout(self, engine: WorkflowEngine) -> None:
        due = engine.calculate_due_date("2026-01-01", "review")
        assert due == "2026-01-08"  # 7 days later

    def test_due_date_none_when_no_timeout(self, engine: WorkflowEngine) -> None:
        assert engine.calculate_due_date("2026-01-01", "draft") is None

    def test_due_date_invalid_date_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(ValueError):
            engine.calculate_due_date("not-a-date", "review")

    def test_due_date_unknown_step_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(KeyError):
            engine.calculate_due_date("2026-01-01", "nonexistent")

    # ── is_final ──────────────────────────────────────────────────────────

    def test_is_final_true(self, engine: WorkflowEngine) -> None:
        assert engine.is_final("approve") is True

    def test_is_final_false(self, engine: WorkflowEngine) -> None:
        assert engine.is_final("draft") is False
        assert engine.is_final("review") is False

    # ── get_step / all_steps ──────────────────────────────────────────────

    def test_get_step_found(self, engine: WorkflowEngine) -> None:
        step = engine.get_step("review")
        assert step is not None
        assert step.role == "reviewer"

    def test_get_step_not_found(self, engine: WorkflowEngine) -> None:
        assert engine.get_step("nonexistent") is None

    def test_all_steps_returns_copy(self, engine: WorkflowEngine) -> None:
        steps = engine.all_steps()
        assert len(steps) == 3
        assert steps[0].name == "draft"
        # Mutation of the returned list should not affect the engine
        steps.pop()
        assert len(engine.all_steps()) == 3


# ── Predefined workflows ─────────────────────────────────────────────────


class TestPredefinedWorkflows:
    def test_rfi_workflow_steps(self) -> None:
        names = [s.name for s in RFI_WORKFLOW.all_steps()]
        assert names == ["draft", "open", "answered", "closed"]

    def test_rfi_open_has_timeout(self) -> None:
        step = RFI_WORKFLOW.get_step("open")
        assert step is not None
        assert step.timeout_days == 14

    def test_rfi_ball_in_court(self) -> None:
        assert RFI_WORKFLOW.ball_in_court("open") == "assigned_to"
        assert RFI_WORKFLOW.ball_in_court("answered") == "author"

    def test_submittal_workflow_steps(self) -> None:
        names = [s.name for s in SUBMITTAL_WORKFLOW.all_steps()]
        assert names == ["draft", "submitted", "under_review", "approved"]

    def test_submittal_advance_chain(self) -> None:
        assert SUBMITTAL_WORKFLOW.advance("draft") == "submitted"
        assert SUBMITTAL_WORKFLOW.advance("submitted") == "under_review"
        assert SUBMITTAL_WORKFLOW.advance("under_review") == "approved"
        assert SUBMITTAL_WORKFLOW.advance("approved") is None

    def test_ncr_workflow_steps(self) -> None:
        names = [s.name for s in NCR_WORKFLOW.all_steps()]
        assert names == [
            "identified",
            "under_review",
            "corrective_action",
            "verification",
            "closed",
        ]

    def test_ncr_ball_in_court_chain(self) -> None:
        assert NCR_WORKFLOW.ball_in_court("identified") == "inspector"
        assert NCR_WORKFLOW.ball_in_court("corrective_action") == "responsible"
        assert NCR_WORKFLOW.ball_in_court("closed") == "manager"

    def test_transmittal_workflow_steps(self) -> None:
        names = [s.name for s in TRANSMITTAL_WORKFLOW.all_steps()]
        assert names == ["draft", "issued", "acknowledged", "responded", "closed"]

    def test_transmittal_final_is_closed(self) -> None:
        assert TRANSMITTAL_WORKFLOW.is_final("closed") is True
        assert TRANSMITTAL_WORKFLOW.is_final("draft") is False

    def test_transmittal_retreat_from_acknowledged(self) -> None:
        assert TRANSMITTAL_WORKFLOW.retreat("acknowledged") == "issued"
