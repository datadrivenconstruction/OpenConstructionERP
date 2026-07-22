# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dry-run simulator for approval routes.

A route author needs to see what a template will do *before* anyone starts a
real workflow on it: how many approvals each step needs, whether a step can
ever clear, and what a single rejection does. This module answers that
question without touching the database.

The single source of truth for "is this step cleared?" lives in
:func:`step_cleared`, which is also called by the live engine
(``service.ApprovalRouteService._maybe_advance``). Keeping one implementation
means the dry run can never drift from what the engine actually does.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.approval_routes.schemas import (
    RouteSimulationResponse,
    SimulateDecision,
    SimulatedStep,
    SimulationOutcome,
)


class StepLike(Protocol):
    """The subset of a :class:`~app.modules.approval_routes.models.Step` the
    simulator reads. Declared as a Protocol so the pure logic can be unit
    tested with lightweight stand-ins and never needs a DB session."""

    ordinal: int
    mode: str
    approver_role: str | None
    approver_user_id: uuid.UUID | None
    required_approver_count: int | None


def step_cleared(
    *,
    mode: str,
    user_pinned: bool,
    pinned_user_approved: bool,
    approvals: int,
    distinct_approvers: int,
    rejections: int,
    total_acted: int,
    quorum: int | None,
) -> bool:
    """Decide whether a single step is cleared from its decision tallies.

    This is the exact rule the live engine applies in ``_maybe_advance``,
    lifted out so both the running workflow and the dry run share one
    definition.

    Args:
        mode: Step mode - ``"all"``, ``"any"`` or ``"majority"``.
        user_pinned: ``True`` when the step names a specific ``approver_user_id``.
        pinned_user_approved: For a user-pinned step, whether that user approved.
        approvals: Count of ``approved`` decision rows.
        distinct_approvers: Count of distinct approvers among the approvals.
        rejections: Count of ``rejected`` decision rows.
        total_acted: Count of rows that are not ``pending`` (approvals + rejections).
        quorum: The step's declared ``required_approver_count`` (may be ``None``).

    Returns:
        ``True`` when the step is cleared and the workflow may advance.
    """
    if user_pinned:
        # A pinned step advances on that one user's approval.
        return pinned_user_approved

    if mode == "any":
        return approvals >= 1

    if mode == "majority":
        if quorum is not None and quorum >= 1:
            return distinct_approvers * 2 > quorum and rejections == 0
        # No declared population: > half of everyone who acted, at least two.
        return total_acted >= 2 and approvals * 2 > total_acted

    # "all" (the default).
    if quorum is not None and quorum >= 1:
        return distinct_approvers >= quorum and rejections == 0
    # No declared population: require at least two distinct approvers so a
    # single approval cannot silently close a gate meant for several.
    return distinct_approvers >= 2 and rejections == 0


def min_approvals_to_clear(step: StepLike) -> int:
    """Fewest clean approvals (no rejections) that would clear ``step``."""
    if step.approver_user_id is not None:
        return 1
    quorum = step.required_approver_count
    if step.mode == "any":
        return 1
    if step.mode == "majority":
        if quorum is not None and quorum >= 1:
            return quorum // 2 + 1
        return 2
    # "all"
    if quorum is not None and quorum >= 1:
        return quorum
    return 2


def _needs_multiple_approvers(step: StepLike) -> bool:
    """A role step whose ``all`` / ``majority`` gate has no declared count
    implicitly needs two different approvers - a common surprise when the
    author meant a single sign-off."""
    return step.approver_user_id is None and step.mode in ("all", "majority") and step.required_approver_count is None


def _describe_approver(step: StepLike) -> str:
    if step.approver_user_id is not None:
        return f"user {step.approver_user_id}"
    if step.approver_role:
        return f"role '{step.approver_role}'"
    return "an approver"


def _step_note(step: StepLike, needs_multiple: bool) -> str:
    who = _describe_approver(step)
    need = min_approvals_to_clear(step)
    plural = "approval" if need == 1 else "approvals"
    if step.approver_user_id is not None:
        return f"Needs {who} to approve."
    if step.mode == "any":
        return f"Any single approval from {who} clears this step."
    if needs_multiple:
        return (
            f"Needs at least {need} different {who} approvers. No approver count "
            f"is declared, so one sign-off is not enough."
        )
    return f"Needs {need} {plural} from {who} ({step.mode})."


def _build_steps(steps: list[StepLike]) -> tuple[list[SimulatedStep], list[str]]:
    ordered = sorted(steps, key=lambda s: s.ordinal)
    out: list[SimulatedStep] = []
    warnings: list[str] = []
    for step in ordered:
        needs_multiple = _needs_multiple_approvers(step)
        out.append(
            SimulatedStep(
                ordinal=step.ordinal,
                mode=step.mode,
                approver_role=step.approver_role,
                approver_user_id=step.approver_user_id,
                quorum_required=step.required_approver_count,
                min_approvals_to_clear=min_approvals_to_clear(step),
                needs_multiple_approvers=needs_multiple,
                note=_step_note(step, needs_multiple),
            )
        )
        if needs_multiple:
            warnings.append(
                f"Step {step.ordinal} ({step.mode}) needs at least two different "
                f"approvers because no required_approver_count is set. Set a count, "
                f"pin a user, or use mode 'any' if one approval should be enough."
            )
        if step.approver_user_id is None and step.mode == "majority" and step.required_approver_count == 1:
            warnings.append(
                f"Step {step.ordinal} is 'majority' with required_approver_count 1, "
                f"so a single approval clears it, same as mode 'any'."
            )
    return out, warnings


def _walk(
    steps: list[StepLike],
    tally: dict[int, tuple[int, int, int]],
) -> SimulationOutcome:
    """Walk the ordered steps applying per-step (approvals, rejections,
    distinct) tallies, returning where the workflow ends up.

    A rejection on the current step ends the whole workflow immediately, which
    is exactly what the engine does when a ``rejected`` decision comes in.
    """
    trace: list[str] = []
    for step in sorted(steps, key=lambda s: s.ordinal):
        approvals, rejections, distinct = tally[step.ordinal]
        if rejections >= 1:
            trace.append(f"Step {step.ordinal}: a rejection is submitted, so the workflow is rejected.")
            return SimulationOutcome(outcome="rejected", stopped_at_ordinal=step.ordinal, trace=trace)
        user_pinned = step.approver_user_id is not None
        cleared = step_cleared(
            mode=step.mode,
            user_pinned=user_pinned,
            pinned_user_approved=approvals >= 1,
            approvals=approvals,
            distinct_approvers=distinct,
            rejections=rejections,
            total_acted=approvals + rejections,
            quorum=step.required_approver_count,
        )
        need = min_approvals_to_clear(step)
        if cleared:
            trace.append(f"Step {step.ordinal} ({step.mode}) clears with {approvals} approval(s).")
            continue
        trace.append(
            f"Step {step.ordinal} ({step.mode}) is not cleared: {approvals} "
            f"approval(s) of {need} needed, so the workflow waits here."
        )
        return SimulationOutcome(outcome="stuck", stopped_at_ordinal=step.ordinal, trace=trace)
    trace.append("Every step cleared, so the workflow is approved.")
    return SimulationOutcome(outcome="completed", stopped_at_ordinal=None, trace=trace)


def simulate_route(
    *,
    route_id: uuid.UUID,
    target_kind: str,
    steps: list[StepLike],
    decisions: list[SimulateDecision],
) -> RouteSimulationResponse:
    """Dry-run a route template and report what it would do.

    The response always includes a happy path (every step gets exactly the
    approvals it needs, no rejections), which is the quickest way to confirm a
    template can actually reach ``approved``. When ``decisions`` are supplied,
    a second what-if walk shows where those specific approvals and rejections
    would leave the workflow.

    Args:
        route_id: The route being simulated (echoed back for the caller).
        target_kind: The route's target kind (echoed back).
        steps: The route's steps (any order; sorted by ordinal internally).
        decisions: Optional per-step hypothetical tallies for a what-if walk.

    Returns:
        A :class:`RouteSimulationResponse` with per-step analysis, the happy
        path outcome, an optional scenario outcome and any design warnings.
    """
    sim_steps, warnings = _build_steps(steps)

    # Happy path: each step gets exactly the approvals it needs, no rejections.
    happy_tally = {s.ordinal: (min_approvals_to_clear(s), 0, min_approvals_to_clear(s)) for s in steps}
    happy_path = _walk(steps, happy_tally)

    scenario: SimulationOutcome | None = None
    if decisions:
        # Start every step at its happy-path minimum, then override the steps
        # the caller spoke about, so a scenario can name just the step it cares
        # about ("what if step 2 is rejected?").
        tally = dict(happy_tally)
        for d in decisions:
            distinct = d.distinct_approvers if d.distinct_approvers is not None else d.approvals
            tally[d.ordinal] = (d.approvals, d.rejections, distinct)
        scenario = _walk(steps, tally)

    return RouteSimulationResponse(
        route_id=route_id,
        target_kind=target_kind,
        step_count=len(sim_steps),
        steps=sim_steps,
        happy_path=happy_path,
        scenario=scenario,
        warnings=warnings,
    )
