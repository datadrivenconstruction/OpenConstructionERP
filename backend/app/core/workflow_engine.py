"""Workflow engine — ball-in-court tracking, approval steps, due dates.

Provides reusable workflow primitives for construction document management.
Used by: RFI, Submittals, NCR, Transmittals, Enterprise Workflows.

This module is stateless and operates on plain dataclasses, making it easy
to test independently of the ORM and database layer.

Usage:
    from app.core.workflow_engine import WorkflowEngine, WorkflowStep

    engine = WorkflowEngine(steps=[
        WorkflowStep(name="submit", role="contractor"),
        WorkflowStep(name="review", role="reviewer"),
        WorkflowStep(name="approve", role="approver"),
    ])

    next_step = engine.advance("submit")  # → "review"
    bic = engine.ball_in_court("review")  # → "reviewer"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """Single step in a linear workflow.

    Attributes:
        name: Unique step identifier (e.g. "draft", "open", "closed").
        role: Role responsible at this step (e.g. "author", "reviewer").
        auto_advance: Auto-proceed to the next step when conditions are met.
        timeout_days: Number of calendar days before the step is considered overdue.
            ``None`` means no deadline.
    """

    name: str
    role: str
    auto_advance: bool = False
    timeout_days: int | None = None


class WorkflowEngine:
    """Linear workflow engine with ball-in-court tracking.

    Steps are ordered — ``advance`` moves forward, ``retreat`` moves backward.
    The engine is **stateless**: it does not store the current step of any
    particular document.  Persistence is the caller's responsibility.
    """

    def __init__(self, steps: list[WorkflowStep]) -> None:
        if not steps:
            raise ValueError("A workflow must contain at least one step")

        seen: set[str] = set()
        for step in steps:
            if step.name in seen:
                raise ValueError(f"Duplicate step name: {step.name!r}")
            seen.add(step.name)

        self._steps = list(steps)
        self._index: dict[str, int] = {s.name: i for i, s in enumerate(steps)}

    # ── Navigation ────────────────────────────────────────────────────────

    def advance(self, current_step: str) -> str | None:
        """Return the next step name, or ``None`` if *current_step* is final."""
        idx = self._resolve_index(current_step)
        if idx + 1 >= len(self._steps):
            return None
        return self._steps[idx + 1].name

    def retreat(self, current_step: str) -> str | None:
        """Return the previous step name, or ``None`` if *current_step* is first."""
        idx = self._resolve_index(current_step)
        if idx <= 0:
            return None
        return self._steps[idx - 1].name

    # ── Queries ───────────────────────────────────────────────────────────

    def ball_in_court(self, current_step: str) -> str:
        """Return the role responsible for *current_step*."""
        return self._resolve_step(current_step).role

    def calculate_due_date(self, start_date: str, step_name: str) -> str | None:
        """Calculate the ISO-format due date for a step.

        Args:
            start_date: ISO-8601 date string (``YYYY-MM-DD``).
            step_name: Step whose ``timeout_days`` to use.

        Returns:
            ISO date string, or ``None`` if the step has no timeout.

        Raises:
            KeyError: If *step_name* is not part of the workflow.
            ValueError: If *start_date* cannot be parsed.
        """
        step = self._resolve_step(step_name)
        if step.timeout_days is None:
            return None
        start = date.fromisoformat(start_date)
        due = start + timedelta(days=step.timeout_days)
        return due.isoformat()

    def is_final(self, step_name: str) -> bool:
        """Return ``True`` if *step_name* is the last step in the workflow."""
        idx = self._resolve_index(step_name)
        return idx == len(self._steps) - 1

    def get_step(self, name: str) -> WorkflowStep | None:
        """Return the :class:`WorkflowStep` with *name*, or ``None``."""
        idx = self._index.get(name)
        if idx is None:
            return None
        return self._steps[idx]

    def all_steps(self) -> list[WorkflowStep]:
        """Return a shallow copy of the ordered step list."""
        return list(self._steps)

    # ── Internals ─────────────────────────────────────────────────────────

    def _resolve_index(self, step_name: str) -> int:
        """Look up step index, raising ``KeyError`` on miss."""
        try:
            return self._index[step_name]
        except KeyError:
            raise KeyError(f"Unknown workflow step: {step_name!r}") from None

    def _resolve_step(self, step_name: str) -> WorkflowStep:
        return self._steps[self._resolve_index(step_name)]

    # ── Dunder helpers ────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._steps)

    def __repr__(self) -> str:
        names = " → ".join(s.name for s in self._steps)
        return f"WorkflowEngine([{names}])"


# ── Predefined workflows ──────────────────────────────────────────────────

RFI_WORKFLOW = WorkflowEngine(
    steps=[
        WorkflowStep(name="draft", role="author"),
        WorkflowStep(name="open", role="assigned_to", timeout_days=14),
        WorkflowStep(name="answered", role="author"),
        WorkflowStep(name="closed", role="author"),
    ]
)

SUBMITTAL_WORKFLOW = WorkflowEngine(
    steps=[
        WorkflowStep(name="draft", role="author"),
        WorkflowStep(name="submitted", role="reviewer"),
        WorkflowStep(name="under_review", role="reviewer"),
        WorkflowStep(name="approved", role="approver"),
    ]
)

NCR_WORKFLOW = WorkflowEngine(
    steps=[
        WorkflowStep(name="identified", role="inspector"),
        WorkflowStep(name="under_review", role="reviewer"),
        WorkflowStep(name="corrective_action", role="responsible"),
        WorkflowStep(name="verification", role="inspector"),
        WorkflowStep(name="closed", role="manager"),
    ]
)

TRANSMITTAL_WORKFLOW = WorkflowEngine(
    steps=[
        WorkflowStep(name="draft", role="author"),
        WorkflowStep(name="issued", role="recipient"),
        WorkflowStep(name="acknowledged", role="recipient"),
        WorkflowStep(name="responded", role="author"),
        WorkflowStep(name="closed", role="author"),
    ]
)
