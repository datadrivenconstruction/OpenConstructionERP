# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Estimate Builder REST router.

Auto-mounted by the module loader at ``/api/v1/ai-estimator/`` (the kebab form
of the ``oe_ai_estimator`` slug; a legacy ``/api/v1/ai_estimator`` mirror is
mounted too). Implements ``docs/initiative-ai-estimator/API_CONTRACT.md``.

Every project-scoped endpoint runs ``verify_project_access`` (404 on deny so a
UUID's existence is not leaked) and an explicit permission check via
``permission_registry``. Money is emitted as decimal strings, confidence is a
real float or null, and currencies are never blended (the schemas enforce all
three). Errors are surfaced as clean HTTP envelopes - no 500s for missing keys
or absent vectors (the run degrades and ``progress.degraded_reason`` explains).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.ai_estimator import schemas
from app.modules.ai_estimator.intake import IntakeService
from app.modules.ai_estimator.models import (
    AiEstimatorGroup,
    AiEstimatorIntake,
    AiEstimatorRun,
)
from app.modules.ai_estimator.repository import (
    AiEstimatorGroupRepository,
    AiEstimatorIntakeRepository,
    AiEstimatorRunRepository,
)
from app.modules.ai_estimator.service import AiEstimatorService

router = APIRouter(tags=["ai_estimator"])


def _uid(current_user_id: str) -> uuid.UUID:
    return uuid.UUID(current_user_id)


async def _load_run(
    session: SessionDep,
    run_id: uuid.UUID,
    current_user_id: str,
) -> AiEstimatorRun:
    """Load a run and authorise the caller against its project (404 on deny).

    The action verb (read / run / apply) is gated separately by a
    ``RequirePermission`` route dependency; this handles existence + project
    membership so a UUID's existence is never leaked.
    """
    run = await AiEstimatorRunRepository(session).get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Estimate run not found")
    await verify_project_access(run.project_id, current_user_id, session)
    return run


async def _load_group(
    session: SessionDep,
    run: AiEstimatorRun,
    group_id: uuid.UUID,
) -> AiEstimatorGroup:
    """Load a group and assert it belongs to the run (404 otherwise)."""
    grp = await AiEstimatorGroupRepository(session).get_by_id(group_id)
    if grp is None or grp.run_id != run.id:
        raise HTTPException(status_code=404, detail="Estimate group not found")
    return grp


async def _load_intake(session: SessionDep, run: AiEstimatorRun) -> AiEstimatorIntake:
    """Load the 1:1 intake row for a run (404 when the run has no intake)."""
    intake = await AiEstimatorIntakeRepository(session).get_for_run(run.id)
    if intake is None:
        raise HTTPException(status_code=404, detail="This run has no conversational intake.")
    return intake


# ── Conversational intake (v2) ───────────────────────────────────────────────


@router.post(
    "/intake",
    response_model=schemas.IntakeState,
    status_code=201,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def create_intake(
    spec: schemas.IntakeCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.IntakeState:
    """Start a conversational intake from a free-text request.

    Creates a run in status ``intake`` plus an intake row, runs the extraction
    step (AI or deterministic), and returns the first :class:`IntakeState`.
    Grouping does NOT run yet - the user confirms a parameter sheet and a group
    board first.
    """
    await verify_project_access(spec.project_id, current_user_id, session)
    service = IntakeService(session)
    run, intake = await service.start(spec, _uid(current_user_id))
    return await service.to_state(run, intake)


@router.get(
    "/runs/{run_id}/intake",
    response_model=schemas.IntakeState,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def get_intake(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.IntakeState:
    """Poll the intake state (while extraction / a round / compose runs)."""
    run = await _load_run(session, run_id, current_user_id)
    intake = await _load_intake(session, run)
    return await IntakeService(session).to_state(run, intake)


@router.post(
    "/runs/{run_id}/intake/answer",
    response_model=schemas.IntakeState,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def answer_intake(
    run_id: uuid.UUID,
    spec: schemas.IntakeAnswerRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.IntakeState:
    """Record the current round's answers and (optionally) advance the FSM.

    Advancing never exceeds three clarification rounds: a third advancing
    answer always lands on the parameter sheet, never a fourth round.
    """
    run = await _load_run(session, run_id, current_user_id)
    intake = await _load_intake(session, run)
    service = IntakeService(session)
    intake = await service.answer(run, intake, spec)
    refreshed = await _load_run(session, run_id, current_user_id)
    return await service.to_state(refreshed, intake)


@router.post(
    "/runs/{run_id}/intake/confirm-parameters",
    response_model=schemas.IntakeState,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def confirm_parameters(
    run_id: uuid.UUID,
    spec: schemas.ConfirmParametersRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.IntakeState:
    """Confirm the parameter sheet (checkpoint A) and compose the group board.

    Runs the hybrid checklist + live vector-probe composer and persists the
    composed groups, then transitions to ``group_board``.
    """
    run = await _load_run(session, run_id, current_user_id)
    intake = await _load_intake(session, run)
    service = IntakeService(session)
    intake = await service.confirm_parameters(run, intake, spec)
    refreshed = await _load_run(session, run_id, current_user_id)
    return await service.to_state(refreshed, intake)


@router.post(
    "/runs/{run_id}/intake/packages",
    response_model=schemas.IntakeState,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def edit_intake_packages(
    run_id: uuid.UUID,
    spec: schemas.IntakePackagesRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.IntakeState:
    """Edit the package board: add / remove / toggle packages.

    Editing a package re-probes it (honest: the coverage badge reflects the
    real live probe); removing a package deletes its composed groups.
    """
    run = await _load_run(session, run_id, current_user_id)
    intake = await _load_intake(session, run)
    service = IntakeService(session)
    intake = await service.edit_packages(run, intake, spec)
    refreshed = await _load_run(session, run_id, current_user_id)
    return await service.to_state(refreshed, intake)


@router.post(
    "/runs/{run_id}/intake/finish",
    response_model=schemas.RunRead,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def finish_intake(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunRead:
    """Confirm the group board (checkpoint B) and bridge to the run pipeline.

    Advances the run to the same state the legacy source checkpoint produced
    (status ``grouping``), keeping the composed groups, so the rest of the
    pipeline (match / preview / apply) runs unchanged.
    """
    run = await _load_run(session, run_id, current_user_id)
    intake = await _load_intake(session, run)
    service = IntakeService(session)
    run = await service.finish(run, intake, _uid(current_user_id))
    return AiEstimatorService(session).run_to_read(run)


@router.get(
    "/project-types",
    response_model=list[schemas.ProjectTypeOut],
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def list_project_types(_current_user_id: CurrentUserId) -> list[schemas.ProjectTypeOut]:
    """Return the static project-type registry for the intake UI (tiles + schema).

    Every user-facing label is an i18n key (``aiest.ptype.<key>`` /
    ``aiest.param.<key>`` / ``aiest.pkg.<key>``); the synonyms are included so
    the UI can show "matched on ..." hints.
    """
    from app.modules.ai_estimator.project_types import PROJECT_TYPE_ORDER, get_project_type

    out: list[schemas.ProjectTypeOut] = []
    for key in PROJECT_TYPE_ORDER:
        pt = get_project_type(key)
        if pt is None:
            continue
        out.append(
            schemas.ProjectTypeOut(
                key=pt.key,
                label_key=f"aiest.ptype.{pt.key}",
                synonyms=[*pt.synonyms_en, *pt.synonyms_ru, *pt.synonyms_de],
                params=[
                    schemas.ProjectParamOut(
                        key=p.key,
                        kind=p.kind,  # type: ignore[arg-type]
                        unit=p.unit,
                        required=p.required,
                        choices=list(p.choices or ()),
                        unlocks=list(p.unlocks),
                        round_group=p.round_group,
                        label_key=f"aiest.param.{p.key}",
                        why_key=f"aiest.why.{p.key}",
                    )
                    for p in pt.params
                ],
                packages=[
                    schemas.WorkPackageOut(
                        key=pkg.key,
                        trade=pkg.trade,
                        default_on=pkg.default_on,
                        stages=list(pkg.stages),
                        unit=pkg.unit,
                        label_key=f"aiest.pkg.{pkg.key}",
                    )
                    for pkg in pt.packages
                ],
                default_unit_system=pt.default_unit_system,
            )
        )
    return out


# ── Runs ───────────────────────────────────────────────────────────────────


@router.post(
    "/runs",
    response_model=schemas.RunRead,
    status_code=201,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def create_run(
    spec: schemas.RunCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunRead:
    await verify_project_access(spec.project_id, current_user_id, session)
    service = AiEstimatorService(session)
    run = await service.create_run(spec, _uid(current_user_id))
    # Start stage 1 immediately (the wizard polls progress while it runs).
    run = await service.analyze(run, use_ai=True)
    return service.run_to_read(run)


@router.get(
    "/runs",
    response_model=schemas.RunListResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def list_runs(
    session: SessionDep,
    current_user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> schemas.RunListResponse:
    if project_id is not None:
        await verify_project_access(project_id, current_user_id, session)
    repo = AiEstimatorRunRepository(session)
    runs = await repo.list_runs(project_id=project_id, limit=limit, offset=offset)
    total = await repo.count_runs(project_id=project_id)
    service = AiEstimatorService(session)
    summaries = [await service.run_to_summary(r) for r in runs]
    return schemas.RunListResponse(total=total, runs=summaries)


@router.get(
    "/runs/{run_id}",
    response_model=schemas.RunRead,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def get_run(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunRead:
    run = await _load_run(session, run_id, current_user_id)
    return AiEstimatorService(session).run_to_read(run)


@router.post(
    "/runs/{run_id}/sources",
    response_model=schemas.RunRead,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def add_sources(
    run_id: uuid.UUID,
    spec: schemas.AddSourcesRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunRead:
    run = await _load_run(session, run_id, current_user_id)
    service = AiEstimatorService(session)
    run = await service.add_sources(run, spec)
    return service.run_to_read(run)


@router.post(
    "/runs/{run_id}/analyze",
    response_model=schemas.RunRead,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def analyze_run(
    run_id: uuid.UUID,
    spec: schemas.AnalyzeRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunRead:
    run = await _load_run(session, run_id, current_user_id)
    service = AiEstimatorService(session)
    run = await service.analyze(run, use_ai=spec.use_ai)
    return service.run_to_read(run)


@router.post(
    "/runs/{run_id}/confirm",
    response_model=schemas.RunRead,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def confirm_stage(
    run_id: uuid.UUID,
    spec: schemas.StageConfirmRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunRead:
    run = await _load_run(session, run_id, current_user_id)
    service = AiEstimatorService(session)
    run = await service.confirm_stage(run, spec, _uid(current_user_id))
    return service.run_to_read(run)


@router.get(
    "/runs/{run_id}/progress",
    response_model=schemas.ProgressResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def get_progress(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.ProgressResponse:
    run = await _load_run(session, run_id, current_user_id)
    return await AiEstimatorService(session).build_progress(run)


@router.get(
    "/runs/{run_id}/steps",
    response_model=list[schemas.StepOut],
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def get_steps(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
    limit: int = Query(200, ge=1, le=2000),
) -> list[schemas.StepOut]:
    run = await _load_run(session, run_id, current_user_id)
    from app.modules.ai_estimator.repository import AiEstimatorStepRepository

    steps = await AiEstimatorStepRepository(session).list_for_run(run.id, limit=limit)
    return [schemas.StepOut.model_validate(s) for s in steps]


@router.post(
    "/runs/{run_id}/cancel",
    response_model=schemas.RunRead,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def cancel_run(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunRead:
    run = await _load_run(session, run_id, current_user_id)
    service = AiEstimatorService(session)
    run = await service.cancel(run)
    return service.run_to_read(run)


@router.get(
    "/runs/{run_id}/readiness",
    response_model=schemas.ReadinessResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def get_readiness(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.ReadinessResponse:
    run = await _load_run(session, run_id, current_user_id)
    return await AiEstimatorService(session).build_readiness(run)


# ── Groups ───────────────────────────────────────────────────────────────


@router.get(
    "/runs/{run_id}/groups",
    response_model=schemas.GroupListResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def list_groups(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
    status: list[str] | None = Query(None),
) -> schemas.GroupListResponse:
    run = await _load_run(session, run_id, current_user_id)
    return await AiEstimatorService(session).group_list_response(run.id, statuses=status)


@router.get(
    "/runs/{run_id}/groups/{group_id}",
    response_model=schemas.GroupDetail,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def get_group(
    run_id: uuid.UUID,
    group_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    run = await _load_run(session, run_id, current_user_id)
    grp = await _load_group(session, run, group_id)
    return AiEstimatorService(session).group_to_detail(grp)


@router.patch(
    "/runs/{run_id}/groups/{group_id}",
    response_model=schemas.GroupDetail,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def update_group(
    run_id: uuid.UUID,
    group_id: uuid.UUID,
    spec: schemas.GroupUpdate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    run = await _load_run(session, run_id, current_user_id)
    grp = await _load_group(session, run, group_id)
    service = AiEstimatorService(session)
    grp = await service.update_group(grp, spec)
    return service.group_to_detail(grp)


@router.post(
    "/runs/{run_id}/groups/merge",
    response_model=schemas.GroupListResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def merge_groups(
    run_id: uuid.UUID,
    spec: schemas.GroupMergeRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupListResponse:
    run = await _load_run(session, run_id, current_user_id)
    service = AiEstimatorService(session)
    await service.merge_groups(run, spec)
    return await service.group_list_response(run.id)


@router.post(
    "/runs/{run_id}/groups/split",
    response_model=schemas.GroupListResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def split_group(
    run_id: uuid.UUID,
    spec: schemas.GroupSplitRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupListResponse:
    run = await _load_run(session, run_id, current_user_id)
    service = AiEstimatorService(session)
    await service.split_group(run, spec)
    return await service.group_list_response(run.id)


@router.post(
    "/runs/{run_id}/groups/{group_id}/rematch",
    response_model=schemas.GroupDetail,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def rematch_group(
    run_id: uuid.UUID,
    group_id: uuid.UUID,
    spec: schemas.RunMatchRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    run = await _load_run(session, run_id, current_user_id)
    grp = await _load_group(session, run, group_id)
    service = AiEstimatorService(session)
    # The path id wins over any group_ids in the body.
    single = spec.model_copy(update={"group_ids": [grp.id]})
    await service.run_matching(run, single)
    refreshed = await _load_group(session, run, group_id)
    return service.group_to_detail(refreshed)


@router.post(
    "/runs/{run_id}/groups/{group_id}/confirm",
    response_model=schemas.GroupDetail,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def confirm_group(
    run_id: uuid.UUID,
    group_id: uuid.UUID,
    spec: schemas.ConfirmGroupRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    run = await _load_run(session, run_id, current_user_id)
    grp = await _load_group(session, run, group_id)
    service = AiEstimatorService(session)
    grp = await service.confirm_group(grp, spec, _uid(current_user_id))
    return service.group_to_detail(grp)


# ── Matching / bulk-confirm ──────────────────────────────────────────────


@router.post(
    "/runs/{run_id}/match",
    response_model=schemas.GroupListResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def run_match(
    run_id: uuid.UUID,
    spec: schemas.RunMatchRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupListResponse:
    run = await _load_run(session, run_id, current_user_id)
    service = AiEstimatorService(session)
    await service.run_matching(run, spec)
    return await service.group_list_response(run.id)


@router.post(
    "/runs/{run_id}/bulk-confirm",
    response_model=schemas.BulkConfirmResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.run"))],
)
async def bulk_confirm(
    run_id: uuid.UUID,
    spec: schemas.BulkConfirmRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.BulkConfirmResponse:
    run = await _load_run(session, run_id, current_user_id)
    return await AiEstimatorService(session).bulk_confirm(run, spec, _uid(current_user_id))


# ── Assembly preview / apply ─────────────────────────────────────────────


@router.get(
    "/runs/{run_id}/preview",
    response_model=schemas.PreviewResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def get_preview(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.PreviewResponse:
    run = await _load_run(session, run_id, current_user_id)
    return await AiEstimatorService(session).build_preview(run)


@router.post(
    "/runs/{run_id}/apply",
    response_model=schemas.ApplyResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.apply"))],
)
async def apply_run(
    run_id: uuid.UUID,
    spec: schemas.ApplyRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.ApplyResponse:
    run = await _load_run(session, run_id, current_user_id)
    return await AiEstimatorService(session).apply(run, spec, _uid(current_user_id))


# ── Meta (UI-facing constants contract) ──────────────────────────────────


@router.get(
    "/meta",
    response_model=schemas.MetaResponse,
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def get_meta(_current_user_id: CurrentUserId) -> schemas.MetaResponse:
    """Expose the module's UI-facing constants so the frontend never hardcodes
    magic numbers. Every value is read from its single existing definition."""
    from app.modules.ai_estimator.benchmarks import DEFAULT_BAND_FACTOR
    from app.modules.ai_estimator.service import (
        CONFIDENCE_HIGH_THRESHOLD,
        CONFIDENCE_MEDIUM_THRESHOLD,
    )

    return schemas.MetaResponse(
        score_thresholds=schemas.ScoreThresholds(
            high=CONFIDENCE_HIGH_THRESHOLD,
            low=CONFIDENCE_MEDIUM_THRESHOLD,
        ),
        construction_stages=list(schemas.CONSTRUCTION_STAGES),
        match_group_cap=schemas.DEFAULT_MATCH_GROUP_CAP,
        rate_sanity_band_factor=DEFAULT_BAND_FACTOR,
    )


# ── Reuse: catalogues + Qdrant health ────────────────────────────────────


@router.get(
    "/catalogues",
    response_model=list[schemas.CatalogueOption],
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def list_catalogues(_current_user_id: CurrentUserId) -> list[schemas.CatalogueOption]:
    """Reuse the CWICR v3 region registry for the source-config step."""
    from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES

    out: list[schemas.CatalogueOption] = []
    for cat in CWICR_V3_CATALOGUES:
        if not cat.available:
            continue
        label = f"{cat.city} ({cat.country_iso})" if cat.city else cat.region
        out.append(
            schemas.CatalogueOption(
                id=cat.region,
                label=label,
                currency=cat.currency,
                region=cat.region,
                default_classification_standard=cat.default_classification_standard or None,
            )
        )
    return out


@router.get(
    "/qdrant/health",
    dependencies=[Depends(RequirePermission("ai_estimator.read"))],
)
async def qdrant_health(_current_user_id: CurrentUserId) -> dict[str, object]:
    """Reuse the shared Qdrant health probe so the wizard shows vector-DB state."""
    from app.config import get_settings
    from app.core.vector import reset_qdrant_client
    from app.modules.match_elements.qdrant_supervisor import ensure_qdrant_running

    settings = get_settings()
    health = ensure_qdrant_running(settings.qdrant_url, spawn_if_installed=True)
    if getattr(health, "reachable", False) and getattr(health, "spawn_attempted", False):
        reset_qdrant_client()
    return {
        "reachable": getattr(health, "reachable", False),
        "url": getattr(health, "url", None),
        "installed": getattr(health, "installed", False),
        "storage_dir": getattr(health, "storage_dir", ""),
        "message": getattr(health, "message", ""),
        "install_hint": getattr(health, "install_hint", ""),
    }
