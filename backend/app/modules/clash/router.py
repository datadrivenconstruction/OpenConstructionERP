# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Clash detection API routes — mounted by the loader at ``/api/v1/clash``.

Endpoints
    GET    /projects/{project_id}/models                 → models picker
    GET    /projects/{project_id}/runs/                   → list runs
    POST   /projects/{project_id}/runs/                   → create + execute
    GET    /projects/{project_id}/runs/{run_id}           → run + matrix
    DELETE /projects/{project_id}/runs/{run_id}
    GET    /projects/{project_id}/runs/{run_id}/results   → paginated results
    PATCH  /projects/{project_id}/runs/{run_id}/results/{result_id}
    GET    /projects/{project_id}/runs/{run_id}/compare   → run-to-run diff
    GET    /projects/{project_id}/runs/{run_id}/export-csv → results as CSV
    POST   /projects/{project_id}/runs/{run_id}/export-bcf

Auth mirrors the ``bcf`` module exactly: a coarse ``RequirePermission``
gate plus a per-project owner/admin IDOR check so a viewer of one
project can never read another project's clashes.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi import File as FileParam
from fastapi.responses import StreamingResponse
from sqlalchemy import select as _select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.clash.models import ClashIssue as _IssueModel
from app.modules.clash.models import ClashRun as _RunModel
from app.modules.clash.schemas import (
    CLASH_GROUP_BY,
    CLASH_PROPERTY_GROUP_PREFIX,
    CLASH_SEVERITIES,
    ClashApplyRuleRequest,
    ClashApplyRuleResponse,
    ClashBCFExportRequest,
    ClashBCFExportResponse,
    ClashBCFImportResponse,
    ClashCategoriesResponse,
    ClashCategoryItem,
    ClashClusterRead,
    ClashCompareResponse,
    ClashIssuePage,
    ClashIssueRead,
    ClashKpiResponse,
    ClashPropertyFacet,
    ClashResultPage,
    ClashResultResponse,
    ClashResultUpdate,
    ClashRule,
    ClashRuleList,
    ClashRuleSuggestion,
    ClashRunCreate,
    ClashRunDiff,
    ClashRunListItem,
    ClashRunResponse,
    ClashSuppressRequest,
    ClashWatchResponse,
)
from app.modules.clash.service import ClashService

_MAX_EXPORT_ROWS = 25_000
# Upper bound on the BCF import payload. 100 MiB matches the BCF
# module's own gate and the BCFReader default — federated coordination
# packages with hundreds of viewpoints can legitimately exceed 25 MiB.
_MAX_BCF_UPLOAD_BYTES = 100 * 1024 * 1024

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Clash Detection"])


def _get_service(session: SessionDep) -> ClashService:
    return ClashService(session)


async def _require_project_access(session: AsyncSession, project_id: uuid.UUID, user_id: str) -> None:
    """‌⁠‍Verify the caller owns (or is admin on) ``project_id`` (IDOR guard)."""
    from app.modules.projects.repository import ProjectRepository
    from app.modules.users.repository import UserRepository

    project = await ProjectRepository(session).get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    try:
        user = await UserRepository(session).get_by_id(uuid.UUID(str(user_id)))
        if user is not None and getattr(user, "role", "") == "admin":
            return
    except Exception:  # noqa: BLE001 — best-effort admin check
        logger.exception("Admin-role lookup failed during clash access check")
    if str(getattr(project, "owner_id", "")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this project",
        )


@router.get(
    "/projects/{project_id}/models",
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_models(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> list[dict]:
    """‌⁠‍Lightweight BIM-model list for the run-config picker."""
    await _require_project_access(session, project_id, user_id)
    models = await service.repo.models_for_project(project_id)
    return [
        {
            "id": str(m.id),
            "name": getattr(m, "name", None) or getattr(m, "filename", "Model"),
            "element_count": int(getattr(m, "element_count", 0) or 0),
            "status": getattr(m, "status", None),
        }
        for m in models
    ]


@router.get(
    "/projects/{project_id}/categories",
    response_model=ClashCategoriesResponse,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_categories(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
    model_ids: list[uuid.UUID] = Query(default_factory=list),
    group_by: str = Query(default="type"),
) -> ClashCategoriesResponse:
    """Distinct grouping facets for the Set A / Set B pickers.

    ``group_by`` selects the parameter the Set A/B lists are faceted by:
    one of the built-ins ``discipline | type | category | ifc_entity``
    *or* the open-ended ``property:<key>`` form (the literal
    ``property:`` prefix + a raw element-property key — Starlette has
    already URL-decoded it by the time it reaches here). All facets are
    sourced from every clashable element's ``element_type`` /
    ``discipline`` column and its source-native ``properties``. Scoped
    to the project (IDOR-guarded); ``model_ids`` are intersected with
    the project's own models so a caller can never enumerate another
    project's element taxonomy. ``element_types`` / ``disciplines`` are
    kept for backward compatibility; ``available_group_by`` lists only
    the built-in parameters that have data; ``available_properties``
    enumerates the open-ended property keys the UI may group by (always
    populated, regardless of ``group_by``). An unknown built-in or a
    ``property:`` with an empty key falls back to the ``type`` default
    (matching the existing tolerant param-normalisation style).
    """
    await _require_project_access(session, project_id, user_id)
    if group_by.startswith(CLASH_PROPERTY_GROUP_PREFIX):
        # ``property:`` with an empty/blank key is meaningless — degrade
        # to the safe default rather than 422 (same forgiving contract
        # the unknown-built-in branch already uses).
        if not group_by[len(CLASH_PROPERTY_GROUP_PREFIX) :].strip():
            group_by = "type"
    elif group_by not in CLASH_GROUP_BY:
        group_by = "type"
    project_models = {m.id for m in await service.repo.models_for_project(project_id)}
    wanted = [m for m in model_ids if m in project_models] or list(project_models)
    etypes, discs = await service.repo.categories_for_models(wanted)
    (
        groups,
        available,
        available_props,
    ) = await service.repo.grouping_facets_for_models(wanted, group_by)
    # Stable, predictable order for the UI selector.
    ordered_avail = [g for g in CLASH_GROUP_BY if g in available]
    return ClashCategoriesResponse(
        group_by=group_by,
        groups=[ClashCategoryItem(value=v, count=n) for v, n in groups],
        available_group_by=ordered_avail,
        available_properties=[ClashPropertyFacet(key=k, count=n) for k, n in available_props],
        element_types=[ClashCategoryItem(value=v, count=n) for v, n in etypes],
        disciplines=[ClashCategoryItem(value=v, count=n) for v, n in discs],
    )


@router.get(
    "/projects/{project_id}/runs/",
    response_model=list[ClashRunListItem],
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_runs(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> list[ClashRunListItem]:
    await _require_project_access(session, project_id, user_id)
    runs = await service.list_runs(project_id)
    return [ClashRunListItem.model_validate(r) for r in runs]


@router.post(
    "/projects/{project_id}/runs/",
    response_model=ClashRunResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("clash.create"))],
)
async def create_run(
    project_id: uuid.UUID,
    data: ClashRunCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashRunResponse:
    await _require_project_access(session, project_id, user_id)
    run = await service.create_run(project_id, data, user_id)
    return ClashRunResponse.model_validate(run)


@router.get(
    "/projects/{project_id}/runs/{run_id}",
    response_model=ClashRunResponse,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def get_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashRunResponse:
    await _require_project_access(session, project_id, user_id)
    run = await service.get_run(project_id, run_id)
    return ClashRunResponse.model_validate(run)


@router.delete(
    "/projects/{project_id}/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("clash.delete"))],
)
async def delete_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> None:
    await _require_project_access(session, project_id, user_id)
    await service.delete_run(project_id, run_id)


@router.get(
    "/projects/{project_id}/runs/{run_id}/results",
    response_model=ClashResultPage,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_results(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
    status_filter: str | None = Query(default=None, alias="status"),
    clash_type: str | None = Query(default=None),
    discipline: str | None = Query(default=None),
    discipline_a: str | None = Query(
        default=None,
        description=(
            "Filter for clashes whose discipline pair includes this value. "
            "When combined with ``discipline_b`` the row must match the "
            "(a,b) pair in either order — symmetric pair filter."
        ),
    ),
    discipline_b: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    order_by: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> ClashResultPage:
    await _require_project_access(session, project_id, user_id)
    await service.get_run(project_id, run_id)  # 404 if run not in project
    if severity is not None and severity not in CLASH_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid clash severity '{severity}'",
        )
    rows, total = await service.list_results(
        run_id,
        status=status_filter,
        clash_type=clash_type,
        discipline=discipline,
        discipline_a=discipline_a,
        discipline_b=discipline_b,
        severity=severity,
        order_by=order_by,
        offset=offset,
        limit=limit,
    )
    return ClashResultPage(
        items=[ClashResultResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch(
    "/projects/{project_id}/runs/{run_id}/results/{result_id}",
    response_model=ClashResultResponse,
    dependencies=[Depends(RequirePermission("clash.update"))],
)
async def update_result(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    data: ClashResultUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashResultResponse:
    await _require_project_access(session, project_id, user_id)
    add_comment: dict | None = None
    if data.add_comment is not None:
        author = (data.add_comment.author or "").strip()
        if not author:
            author = await service.resolve_author(user_id)
        add_comment = {
            "text": data.add_comment.text,
            "author": author,
            "author_id": data.add_comment.author_id or str(user_id),
            "reply_to": data.add_comment.reply_to or None,
        }
    result = await service.update_result(
        project_id,
        run_id,
        result_id,
        new_status=data.status,
        assigned_to=data.assigned_to,
        due_date=data.due_date,
        severity=data.severity,
        add_comment=add_comment,
        actor=str(user_id),
    )
    return ClashResultResponse.model_validate(result)


@router.get(
    "/projects/{project_id}/runs/{run_id}/compare",
    response_model=ClashCompareResponse,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def compare_runs(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    base_run_id: uuid.UUID = Query(...),
    service: ClashService = Depends(_get_service),
) -> ClashCompareResponse:
    """Diff this run against ``base_run_id`` by clash signature.

    Partitions every clash into ``new`` (only here), ``resolved`` (only
    in the base run) and ``persistent`` (in both). Both runs are
    404-guarded against the project so the comparison can never leak
    another project's clashes.
    """
    await _require_project_access(session, project_id, user_id)
    diff = await service.compare_runs(project_id, run_id, base_run_id)
    return ClashCompareResponse.model_validate(diff)


@router.get(
    "/projects/{project_id}/runs/{run_id}/export-csv",
    dependencies=[Depends(RequirePermission("clash.export"))],
)
async def export_csv(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
    status_filter: str | None = Query(default=None, alias="status"),
    clash_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
) -> StreamingResponse:
    """Stream the run's results as CSV (respects status/type/severity).

    Reuses the same repository query the results list uses so the export
    is always consistent with what the UI shows.
    """
    await _require_project_access(session, project_id, user_id)
    run = await service.get_run(project_id, run_id)
    if severity is not None and severity not in CLASH_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid clash severity '{severity}'",
        )
    rows, _ = await service.list_results(
        run_id,
        status=status_filter,
        clash_type=clash_type,
        severity=severity,
        order_by="severity",
        offset=0,
        limit=_MAX_EXPORT_ROWS,
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "#",
            "Element A",
            "Discipline A",
            "Element B",
            "Discipline B",
            "Type",
            "Severity",
            "Penetration (m)",
            "Distance (m)",
            "Status",
            "Assigned To",
            "Due Date",
        ]
    )
    for i, r in enumerate(rows, start=1):
        writer.writerow(
            [
                i,
                r.a_name,
                r.a_discipline,
                r.b_name,
                r.b_discipline,
                r.clash_type,
                getattr(r, "severity", "medium") or "medium",
                r.penetration_m,
                r.distance_m,
                r.status,
                r.assigned_to or "",
                getattr(r, "due_date", None) or "",
            ]
        )
    csv_text = buf.getvalue()

    safe_name = (
        "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in (run.name or "clash")).strip() or "clash"
    )
    filename = f"clash_{safe_name}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/projects/{project_id}/runs/{run_id}/export-bcf",
    response_model=ClashBCFExportResponse,
    dependencies=[Depends(RequirePermission("clash.export"))],
)
async def export_bcf(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    data: ClashBCFExportRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashBCFExportResponse:
    await _require_project_access(session, project_id, user_id)
    exported, skipped = await service.export_bcf(project_id, run_id, data, author=user_id, user_id=user_id)
    return ClashBCFExportResponse(exported=exported, skipped=skipped)


@router.post(
    "/projects/{project_id}/runs/{run_id}/import-bcf",
    response_model=ClashBCFImportResponse,
    dependencies=[Depends(RequirePermission("clash.import_bcf"))],
)
async def import_bcf(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = FileParam(..., description="A .bcfzip archive (BCF 2.1 or 3.0)"),
    service: ClashService = Depends(_get_service),
) -> ClashBCFImportResponse:
    """Round-trip a BCF archive back into clash triage.

    Each topic's signature (recovered from the description the matching
    export embedded) is looked up against the run's clashes; matched
    rows have their status / assignee / due-date / comments / BCF guid
    patched. Topics with no match are logged + counted. Mirrors the
    BCF module's own ``POST /import`` shape so the UX stays familiar.
    """
    await _require_project_access(session, project_id, user_id)
    try:
        payload = await file.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read the uploaded archive.",
        ) from exc
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded archive is empty.",
        )
    if len(payload) > _MAX_BCF_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="BCF archive exceeds 100 MiB upload cap.",
        )
    matched, unmatched, errors = await service.import_bcf(project_id, run_id, payload, actor=str(user_id))
    return ClashBCFImportResponse(matched=matched, unmatched=unmatched, errors=errors)


@router.post(
    "/projects/{project_id}/runs/{run_id}/results/{result_id}/watch",
    response_model=ClashWatchResponse,
    dependencies=[Depends(RequirePermission("clash.update"))],
)
async def watch_result(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashWatchResponse:
    """Subscribe the calling user to this clash (idempotent)."""
    await _require_project_access(session, project_id, user_id)
    watchers, watching = await service.set_watch(project_id, run_id, result_id, str(user_id), watching=True)
    return ClashWatchResponse(watchers=watchers, watching=watching)


@router.delete(
    "/projects/{project_id}/runs/{run_id}/results/{result_id}/watch",
    response_model=ClashWatchResponse,
    dependencies=[Depends(RequirePermission("clash.update"))],
)
async def unwatch_result(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashWatchResponse:
    """Unsubscribe the calling user from this clash (idempotent)."""
    await _require_project_access(session, project_id, user_id)
    watchers, watching = await service.set_watch(project_id, run_id, result_id, str(user_id), watching=False)
    return ClashWatchResponse(watchers=watchers, watching=watching)


# ── Wave A4 — clusters / rules / suggestions / KPI ────────────────────────


@router.get(
    "/projects/{project_id}/runs/{run_id}/clusters",
    response_model=list[ClashClusterRead],
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_clusters(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> list[ClashClusterRead]:
    """Spatial clusters discovered for this run (chip group source).

    Empty list when the run pre-dates the cluster pass, has no clashes,
    or had every clash classified as DBSCAN noise. Each entry carries
    its derived heuristic label, member size, dominant discipline pair
    and dominant storey — exactly what the frontend chip group needs.
    """
    await _require_project_access(session, project_id, user_id)
    rows = await service.list_clusters(project_id, run_id)
    return [ClashClusterRead.model_validate(r) for r in rows]


@router.get(
    "/projects/{project_id}/runs/{run_id}/rule-suggestions",
    response_model=list[ClashRuleSuggestion],
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_rule_suggestions(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> list[ClashRuleSuggestion]:
    """Engine-mined rule proposals from the run's false-positive history.

    Empty when no discipline pair has crossed the suggestion threshold,
    or every candidate pair already has a rule. The UI hides the banner
    in either case — no special-case empty response.
    """
    await _require_project_access(session, project_id, user_id)
    suggestions = await service.rule_suggestions(project_id, run_id)
    return [ClashRuleSuggestion.model_validate(s) for s in suggestions]


@router.post(
    "/projects/{project_id}/runs/{run_id}/apply-rule-suggestion",
    response_model=ClashApplyRuleResponse,
    dependencies=[Depends(RequirePermission("clash.manage_rules"))],
)
async def apply_rule_suggestion(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    data: ClashApplyRuleRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashApplyRuleResponse:
    """Append the proposed rule to the run + re-evaluate existing results.

    Adds the proposed :class:`ClashRule` to ``run.rules`` (unless the
    pair already has one) and flips any hard clash on the pair whose
    measured penetration now sits at or below ``tolerance_m`` to
    ``status='ignored'`` — with a history audit-trail entry so the
    Activity tab shows the change.
    """
    await _require_project_access(session, project_id, user_id)
    rule_added, affected = await service.apply_rule_suggestion(
        project_id,
        run_id,
        discipline_a=data.discipline_a,
        discipline_b=data.discipline_b,
        tolerance_m=data.tolerance_m,
        actor=str(user_id),
    )
    return ClashApplyRuleResponse(rule_added=rule_added, results_affected=affected)


@router.get(
    "/projects/{project_id}/runs/{run_id}/rules",
    response_model=list[ClashRule],
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_rules(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> list[ClashRule]:
    """Current rule set persisted on the run (raw JSON column projection)."""
    await _require_project_access(session, project_id, user_id)
    rules = await service.list_rules(project_id, run_id)
    return [ClashRule.model_validate(r) for r in rules]


@router.patch(
    "/projects/{project_id}/runs/{run_id}/rules",
    response_model=list[ClashRule],
    dependencies=[Depends(RequirePermission("clash.manage_rules"))],
)
async def replace_rules(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    data: ClashRuleList,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> list[ClashRule]:
    """Replace the entire rule list (idempotent PUT-style PATCH).

    Pydantic's ``max_length=500`` rejects oversized payloads before they
    reach the service; the service additionally truncates as defence in
    depth. Returns the canonical post-save list so the editor stays in
    sync after one round-trip.
    """
    await _require_project_access(session, project_id, user_id)
    rules = await service.replace_rules(
        project_id,
        run_id,
        [r.model_dump() for r in data.rules],
    )
    return [ClashRule.model_validate(r) for r in rules]


# ── v41 — Smart-issue + signature endpoints ──────────────────────────────


@router.get(
    "/issues",
    response_model=ClashIssuePage,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_issues(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Project to scope by"),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ClashService = Depends(_get_service),
) -> ClashIssuePage:
    """List smart issues for a project, optionally filtered by status.

    Each row carries the member-clash count (the number of
    :class:`ClashResult` rows currently pointing at the issue). Status
    filter must be one of the canonical smart-issue states (validated by
    the service layer).
    """
    await _require_project_access(session, project_id, user_id)
    rows, total = await service.list_issues(
        project_id,
        status_filter=status_filter,
        offset=offset,
        limit=limit,
    )
    items: list[ClashIssueRead] = []
    for issue, count in rows:
        payload = ClashIssueRead.model_validate(issue)
        payload.member_count = int(count)
        # ``due_date`` on the model is a date; serialise as ISO string for
        # the response. Pydantic v2 doesn't auto-coerce ``date`` → ``str``.
        if getattr(issue, "due_date", None) is not None:
            try:
                payload.due_date = issue.due_date.isoformat()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                payload.due_date = None
        items.append(payload)
    return ClashIssuePage(items=items, total=int(total), offset=offset, limit=limit)


@router.post(
    "/issues/{issue_id}/suppress",
    response_model=ClashIssueRead,
    dependencies=[Depends(RequirePermission("clash.update"))],
)
async def suppress_issue(
    issue_id: uuid.UUID,
    data: ClashSuppressRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashIssueRead:
    """Suppress a smart issue's signature — flip it to ``ignored``.

    Adds a :class:`ClashSuppression` row scoped to the issue's project
    (per-project isolation) and flips the issue's status to ``ignored``.
    The matching signature won't auto-resurface in future runs while the
    suppression is in place.
    """
    # Resolve project from any existing issue lookup so we can IDOR-check
    # without a project_id query parameter. We do that by querying any
    # issue with this id and using its project_id; if none exists → 404.
    raw = (await session.execute(_select(_IssueModel).where(_IssueModel.id == issue_id))).scalar_one_or_none()
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash issue not found")
    await _require_project_access(session, raw.project_id, user_id)
    issue = await service.suppress_by_issue(raw.project_id, issue_id, data.reason, user_id)
    return ClashIssueRead.model_validate(issue)


@router.post(
    "/issues/{issue_id}/unsuppress",
    response_model=ClashIssueRead,
    dependencies=[Depends(RequirePermission("clash.update"))],
)
async def unsuppress_issue(
    issue_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashIssueRead:
    """Lift a suppression — flip the issue from ``ignored`` back to ``persisted``."""
    raw = (await session.execute(_select(_IssueModel).where(_IssueModel.id == issue_id))).scalar_one_or_none()
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash issue not found")
    await _require_project_access(session, raw.project_id, user_id)
    issue = await service.unsuppress_by_issue(raw.project_id, issue_id, user_id)
    return ClashIssueRead.model_validate(issue)


@router.get(
    "/runs/{run_id}/diff",
    response_model=ClashRunDiff,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def run_signature_diff(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashRunDiff:
    """Smart-issue diff counts (``new``/``persisted``/``resolved``/``reopened``/``ignored``).

    Computed by comparing the run's signature set against the project's
    known smart issues and the prior run. IDOR-guarded via the run's own
    ``project_id``.
    """
    raw = (await session.execute(_select(_RunModel).where(_RunModel.id == run_id))).scalar_one_or_none()
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash run not found")
    await _require_project_access(session, raw.project_id, user_id)
    diff = await service.run_diff(raw.project_id, run_id)
    return ClashRunDiff(**diff)


@router.get(
    "/projects/{project_id}/runs/{run_id}/kpi",
    response_model=ClashKpiResponse,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def get_kpi(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashService = Depends(_get_service),
) -> ClashKpiResponse:
    """Aggregate dashboard projection for the KPI tab.

    Computed in-memory from the run's results — one query, no extra
    joins. ``mttr_hours`` is ``None`` when no row has resolved yet (the
    UI hides that tile rather than showing ``0``).
    """
    await _require_project_access(session, project_id, user_id)
    payload = await service.compute_kpi(project_id, run_id)
    return ClashKpiResponse.model_validate(payload)
