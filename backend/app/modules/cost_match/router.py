# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost-match API routes.

Mounted at ``/api/v1/cost-match/`` by the module loader.

Endpoint groups:
    /runs/                          - submit a batch, list a project's runs
    /runs/{id}                      - run header with aggregated counts
    /runs/{id}/results              - paged results of one run
    /runs/{id}/review-queue         - the lines still waiting for a person
    /runs/{id}/validate             - the ``cost_match`` rule set, whole run
    /results/{id}                   - one line with its evidence and rulings
    /results/{id}/decision          - confirm, override or reject the line
    /results/{id}/validate          - the ``cost_match`` rule set, one line

Tenant scoping follows the platform's IDOR posture: a request for an object
the caller cannot see returns **404, never 403**, so probing never leaks the
existence of a row.

One route here is deliberately odd. ``_health`` keeps its literal
``/cost-match/_health`` path, which combines with the loader's own
``/api/v1/cost-match`` prefix into a doubled URL. That doubled URL is where the
module-loader health roll-up already looks, and moving it would be a silent
break in an unrelated subsystem for a cosmetic gain. New routes are declared
without the redundant segment, so the business surface is clean.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.permissions import Role, permission_registry
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.cost_match.manifest import manifest
from app.modules.cost_match.models import (
    DECISION_STATES,
    TIERS,
    MatchResult,
    MatchRun,
)
from app.modules.cost_match.schemas import (
    CostMatchValidationReport,
    MatchDecisionCreate,
    MatchDecisionResponse,
    MatchResultPage,
    MatchResultResponse,
    MatchRunCreate,
    MatchRunResponse,
    MatchRunUpdate,
)
from app.modules.cost_match.service import (
    CostMatchService,
    DecisionPayloadError,
    NoSuggestionToConfirmError,
    RunClosedError,
)

router = APIRouter(tags=["Cost Match"])

# Registered at import time, like every other module's permission block: the
# loader imports this router during ``load_all`` (after the core permissions
# are in place) and the registry is never cleared afterwards.
#
# Reading a run is a viewer-level action. Submitting a batch and ruling on a
# line are not: a ruling is the human confirmation the whole workflow rests
# on, so it is gated at EDITOR rather than left open to anyone who can read
# the project.
permission_registry.register_module_permissions(
    "cost_match",
    {
        "cost_match.read": Role.VIEWER,
        "cost_match.run": Role.EDITOR,
        "cost_match.review": Role.EDITOR,
    },
)

_TIER_VALUES = set(TIERS)
_DECISION_STATE_VALUES = set(DECISION_STATES)


def _as_uuid(raw: str | None) -> uuid.UUID | None:
    """Parse an authenticated subject id into a UUID, or ``None``.

    Tokens carry the subject as a string. A deployment that issues a
    non-UUID subject must not crash the review endpoint; the missing
    attribution is then reported by ``cost_match.decision_has_reviewer``
    rather than swallowed.
    """
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


async def _load_run_or_404(session, run_id: uuid.UUID) -> MatchRun:
    run = await session.get(MatchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Match run not found")
    return run


async def _verify_run_access(session, run_id: uuid.UUID, user_id: str) -> MatchRun:
    run = await _load_run_or_404(session, run_id)
    await verify_project_access(run.project_id, user_id, session)
    return run


async def _verify_result_access(
    session,
    result_id: uuid.UUID,
    user_id: str,
) -> tuple[MatchRun, MatchResult]:
    """Load one result plus its run, with the project access check applied.

    The result carries its own ``project_id``, but the run is needed anyway to
    scope an override to the right cost base and to refuse rulings on a closed
    run, so both are resolved here once.
    """
    result = await session.get(MatchResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Match result not found")
    run = await _load_run_or_404(session, result.run_id)
    await verify_project_access(result.project_id, user_id, session)
    return run, result


def _validate_tier(tier: str | None) -> str | None:
    if tier and tier not in _TIER_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown tier '{tier}'; expected one of {', '.join(sorted(_TIER_VALUES))}",
        )
    return tier


def _validate_decision_state(state: str | None) -> str | None:
    if state and state not in _DECISION_STATE_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown decision state '{state}'; expected one of {', '.join(sorted(_DECISION_STATE_VALUES))}",
        )
    return state


@router.get("/cost-match/_health", include_in_schema=False)
async def module_health() -> dict[str, str]:
    return {
        "module": manifest.name,
        "version": manifest.version,
        "status": "healthy",
    }


# ── Runs ─────────────────────────────────────────────────────────────────


@router.post(
    "/runs/",
    response_model=MatchRunResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("cost_match.run"))],
)
async def create_run(
    data: MatchRunCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> MatchRunResponse:
    """Match a pasted batch of descriptions against one cost base.

    Scored synchronously: a few hundred lines against a bounded candidate
    pool is a request, not a job, and the surveyor gets the queue back in the
    same round trip. Nothing is applied - every line comes back pending and
    waits for a person, whatever tier it landed in.
    """
    await verify_project_access(data.project_id, user_id, session)
    service = CostMatchService(session)
    run = await service.create_run(data, created_by=_as_uuid(user_id))
    return await service.run_response(run)


@router.get("/runs/", response_model=list[MatchRunResponse])
async def list_runs(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    run_status: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MatchRunResponse]:
    """Match runs on one project, newest first, each with its live counts.

    The counts come from one grouped query over every listed run's results,
    not from stored columns, so the queue badge on the list can never
    disagree with the queue itself.
    """
    await verify_project_access(project_id, user_id, session)
    service = CostMatchService(session)
    runs = await service.run_repo.list_for_project(
        project_id,
        status=run_status,
        offset=offset,
        limit=limit,
    )
    counts = await service.counts_for_runs([run.id for run in runs])
    responses: list[MatchRunResponse] = []
    for run in runs:
        response = MatchRunResponse.model_validate(run)
        if run.id in counts:
            response.counts = counts[run.id]
        responses.append(response)
    return responses


@router.get("/runs/{run_id}", response_model=MatchRunResponse)
async def get_run(
    run_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> MatchRunResponse:
    run = await _verify_run_access(session, run_id, user_id)
    service = CostMatchService(session)
    return await service.run_response(run)


@router.patch(
    "/runs/{run_id}",
    response_model=MatchRunResponse,
    dependencies=[Depends(RequirePermission("cost_match.review"))],
)
async def update_run(
    run_id: uuid.UUID,
    data: MatchRunUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> MatchRunResponse:
    """Rename a run, re-label its source, or open and close its review.

    Closing is how the surveyor says the pricing is settled: a closed run
    refuses further rulings until it is re-opened, so a late edit cannot move
    a bill that has already been quoted from.
    """
    run = await _verify_run_access(session, run_id, user_id)
    service = CostMatchService(session)
    run = await service.update_run(run, data)
    return await service.run_response(run)


@router.delete(
    "/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("cost_match.run"))],
)
async def delete_run(
    run_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Delete a run with its results and their whole ruling history."""
    await _verify_run_access(session, run_id, user_id)
    service = CostMatchService(session)
    await service.run_repo.delete(run_id)


@router.get("/runs/{run_id}/results", response_model=MatchResultPage)
async def list_run_results(
    run_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    tier: str | None = Query(default=None),
    decision_state: str | None = Query(default=None),
    locale: str = Query(default="en"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> MatchResultPage:
    """One page of a run's results in submission order.

    Filterable by tier and by decision state, which together are how the
    review screens slice the same run: "show me the exact ones", "show me
    what I have already overridden".
    """
    run = await _verify_run_access(session, run_id, user_id)
    _validate_tier(tier)
    _validate_decision_state(decision_state)
    service = CostMatchService(session)
    total = await service.result_repo.count_for_run(
        run.id,
        tier=tier,
        decision_state=decision_state,
    )
    items = await service.result_repo.list_for_run(
        run.id,
        tier=tier,
        decision_state=decision_state,
        offset=offset,
        limit=limit,
    )
    return MatchResultPage(
        run_id=run.id,
        total=total,
        offset=offset,
        limit=limit,
        items=[service.result_response(item, locale=locale) for item in items],
    )


@router.get("/runs/{run_id}/review-queue", response_model=MatchResultPage)
async def list_review_queue(
    run_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query(default="en"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> MatchResultPage:
    """The lines that still need a person before anything can be priced.

    The queue is the ``needs_review`` and ``unmatched`` tiers that nobody has
    ruled on yet - the two where the machine is explicitly not claiming an
    answer. Confident and exact lines still require confirmation before they
    are adopted, but they belong in the bulk-review lists, not here; ask for
    them with ``/results?decision_state=pending``.
    """
    run = await _verify_run_access(session, run_id, user_id)
    service = CostMatchService(session)
    total = await service.result_repo.count_for_run(run.id, queue_only=True)
    items = await service.result_repo.list_for_run(
        run.id,
        queue_only=True,
        offset=offset,
        limit=limit,
    )
    return MatchResultPage(
        run_id=run.id,
        total=total,
        offset=offset,
        limit=limit,
        items=[service.result_response(item, locale=locale) for item in items],
    )


@router.post("/runs/{run_id}/validate", response_model=CostMatchValidationReport)
async def validate_run(
    run_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query(default=""),
) -> CostMatchValidationReport:
    """Run the ``cost_match`` rule set over a whole run.

    Both scopes at once: what the batch shows as a batch (rates adopted in
    two currencies, one scope priced two ways, how much queue is left) and
    every line's own findings folded in.
    """
    run = await _verify_run_access(session, run_id, user_id)
    service = CostMatchService(session)
    return await service.validate_run(run, locale=locale)


# ── Results ──────────────────────────────────────────────────────────────


@router.get("/results/{result_id}", response_model=MatchResultResponse)
async def get_result(
    result_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query(default="en"),
) -> MatchResultResponse:
    """One line with its suggestion, its runners-up and its ruling history."""
    _run, result = await _verify_result_access(session, result_id, user_id)
    service = CostMatchService(session)
    loaded = await service.result_repo.get_with_decisions(result.id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Match result not found")
    return service.result_response(loaded, locale=locale)


@router.post(
    "/results/{result_id}/decision",
    response_model=MatchDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("cost_match.review"))],
)
async def decide_result(
    result_id: uuid.UUID,
    data: MatchDecisionCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> MatchDecisionResponse:
    """Confirm, override or reject one suggested match.

    This is the only way a suggestion becomes something the project uses.
    The ruling is appended to the line's history rather than replacing it, so
    a change of mind stays visible, and it records who ruled and what the
    machine was showing at that moment.
    """
    run, result = await _verify_result_access(session, result_id, user_id)
    service = CostMatchService(session)
    try:
        decision = await service.record_decision(
            run,
            result,
            data,
            decided_by=_as_uuid(user_id),
        )
    except RunClosedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except NoSuggestionToConfirmError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except DecisionPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        # Same IDOR rationale as everywhere else: an id the caller may not use
        # is a 404, never a 403 and never a 422.
        raise HTTPException(status_code=404, detail="Cost item not found in this run's cost base") from exc
    return MatchDecisionResponse.model_validate(decision)


@router.get(
    "/results/{result_id}/decisions",
    response_model=list[MatchDecisionResponse],
)
async def list_result_decisions(
    result_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[MatchDecisionResponse]:
    """The full, ordered ruling history of one line."""
    _run, result = await _verify_result_access(session, result_id, user_id)
    service = CostMatchService(session)
    loaded = await service.result_repo.get_with_decisions(result.id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Match result not found")
    return [MatchDecisionResponse.model_validate(d) for d in loaded.decisions]


@router.post("/results/{result_id}/validate", response_model=CostMatchValidationReport)
async def validate_result(
    result_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query(default=""),
) -> CostMatchValidationReport:
    """Run the result-scope ``cost_match`` rules over one line."""
    _run, result = await _verify_result_access(session, result_id, user_id)
    service = CostMatchService(session)
    loaded = await service.result_repo.get_with_decisions(result.id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Match result not found")
    return await service.validate_result(loaded, locale=locale)
