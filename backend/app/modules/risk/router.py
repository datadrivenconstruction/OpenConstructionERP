# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk Register API routes.

Endpoints:
    POST   /                       - Create risk item
    GET    /?project_id=X          - List for project (with filters)
    GET    /{id}                   - Get single risk
    PATCH  /{id}                   - Update risk
    DELETE /{id}                   - Delete risk
    GET    /matrix?project_id=X    - Risk matrix data (5x5 grid)
    GET    /summary?project_id=X   - Aggregated stats
    GET    /projects/{pid}/contingency                     - EMV vs finance contingency
    POST   /projects/{pid}/contingency/drawdowns/{risk_id} - Confirm a drawdown
    DELETE /projects/{pid}/contingency/drawdowns/{risk_id} - Reverse a drawdown
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.bulk_ops import BulkDeleteRequest, BulkStatusRequest
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.risk.schemas import (
    ContingencyDrawdownRequest,
    ContingencyPosition,
    RiskCreate,
    RiskEscalationSweepRequest,
    RiskEscalationSweepResult,
    RiskListResponse,
    RiskMatrixCell,
    RiskMatrixResponse,
    RiskResponse,
    RiskSimulateRequest,
    RiskSimulationResult,
    RiskSummary,
    RiskUpdate,
)
from app.modules.risk.service import RiskService

router = APIRouter(tags=["risk"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> RiskService:
    return RiskService(session)


def _as_float(value: object, default: float = 0.0) -> float:
    """Parse a string/None numeric column to float without raising.

    Numeric values are stored as SQLite-friendly strings; legacy or
    imported rows can hold ``""`` (DB-level numeric defaults were
    intentionally removed). A single unparseable row must not 500 the
    whole list endpoint.
    """
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _risk_to_response(item: object) -> RiskResponse:
    """Build a RiskResponse from a RiskItem ORM object.

    ``risk_score`` is ALWAYS recomputed on the single canonical 0-5 scale
    (probability x severity_numeric) rather than echoing the stored column,
    which is heterogeneous: seeded rows carry a cost-scaled value (e.g.
    ``probability * (impact_cost + days * 5000)``) while API-created rows
    store the 0-5 product. Echoing the raw value made the list "Score"
    column show enormous seed numbers next to 0-5 API numbers
    (F-PFO-RISK-06). Recomputing here keeps the list, detail view and the
    summary endpoint all on one comparable scale.
    """
    from app.modules.risk.service import _compute_risk_score

    probability = _as_float(item.probability, 0.5)  # type: ignore[attr-defined]
    severity = item.impact_severity or "medium"  # type: ignore[attr-defined]
    canonical_score = _compute_risk_score(probability, severity)
    return RiskResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        code=item.code,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        category=item.category,  # type: ignore[attr-defined]
        probability=probability,
        impact_cost=_as_float(item.impact_cost),  # type: ignore[attr-defined]
        impact_schedule_days=item.impact_schedule_days,  # type: ignore[attr-defined]
        impact_severity=item.impact_severity,  # type: ignore[attr-defined]
        risk_score=canonical_score,
        probability_score=getattr(item, "probability_score", None),
        impact_score_cost=getattr(item, "impact_score_cost", None),
        impact_score_time=getattr(item, "impact_score_time", None),
        risk_tier=getattr(item, "risk_tier", None),
        status=item.status,  # type: ignore[attr-defined]
        mitigation_strategy=item.mitigation_strategy,  # type: ignore[attr-defined]
        contingency_plan=item.contingency_plan,  # type: ignore[attr-defined]
        owner_name=item.owner_name,  # type: ignore[attr-defined]
        owner_user_id=getattr(item, "owner_user_id", None),
        response_cost=_as_float(item.response_cost),  # type: ignore[attr-defined]
        currency=item.currency,  # type: ignore[attr-defined]
        escalated=bool(getattr(item, "escalated", False)),
        escalated_at=getattr(item, "escalated_at", None),
        escalation_trigger=getattr(item, "escalation_trigger", None),
        escalation_threshold=getattr(item, "escalation_threshold", None),
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get(
    "/summary/",
    response_model=RiskSummary,
    dependencies=[Depends(RequirePermission("risk.read"))],
)
async def get_summary(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RiskService = Depends(_get_service),
) -> RiskSummary:
    """Aggregated risk stats for a project."""
    await verify_project_access(project_id, user_id, session)
    data = await service.get_summary(project_id)
    return RiskSummary(**data)


# ── Matrix ───────────────────────────────────────────────────────────────────


@router.get(
    "/matrix/",
    response_model=RiskMatrixResponse,
    dependencies=[Depends(RequirePermission("risk.read"))],
)
async def get_matrix(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RiskService = Depends(_get_service),
) -> RiskMatrixResponse:
    """5x5 risk matrix data for a project."""
    await verify_project_access(project_id, user_id, session)
    cells_data = await service.get_matrix(project_id)
    cells = [RiskMatrixCell(**c) for c in cells_data]
    return RiskMatrixResponse(cells=cells)


# ── Create ───────────────────────────────────────────────────────────────────


@router.post("/", response_model=RiskResponse, status_code=201)
async def create_risk(
    data: RiskCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("risk.create")),
    service: RiskService = Depends(_get_service),
) -> RiskResponse:
    """Create a new risk item."""
    try:
        item = await service.create_risk(data, user_id=str(user_id) if user_id else None)
        return _risk_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create risk item")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create risk item",
        )


# ── List ─────────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=RiskListResponse,
    dependencies=[Depends(RequirePermission("risk.read"))],
)
async def list_risks(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    sort_by: str | None = Query(default=None, description="Sort field: risk_score, probability, created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    service: RiskService = Depends(_get_service),
) -> RiskListResponse:
    """List risk items for a project, with the size of the whole filtered set.

    The service has always returned the count and this route has always
    dropped it on the floor, so the register showed fifty rows and let the
    reader assume that was the register.
    """
    await verify_project_access(project_id, user_id, session)
    items, total = await service.list_risks(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        category_filter=category,
        severity_filter=severity,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return RiskListResponse(
        items=[_risk_to_response(i) for i in items],
        total=total,
        offset=offset,
        limit=limit,
    )


# ── Monte Carlo simulation (v3.11 - T1) ──────────────────────────────────
#
# Mounted under ``/projects/{project_id}/simulate`` (not the bare
# ``/{risk_id}`` parametric) so the parametric-collision rule does not
# apply - FastAPI/Starlette's path router has no ambiguity between
# ``/projects/.../simulate`` and ``/{risk_id}``.


@router.post(
    "/projects/{project_id}/simulate",
    response_model=RiskSimulationResult,
    dependencies=[Depends(RequirePermission("risk.read"))],
)
async def simulate_risks(
    project_id: uuid.UUID,
    body: RiskSimulateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RiskService = Depends(_get_service),
) -> RiskSimulationResult:
    """Run a Monte Carlo simulation across this project's risks.

    Samples a PERT (triangular) distribution on each risk's
    (p10, p50, p90) triple and weights each draw by
    ``probability_score / 5`` to form the project-level contingency
    distribution. Returns P50/P80/P95 percentiles, a 10-bin histogram
    and a tornado-chart sensitivity ranking.

    Persisted on every risk row's ``last_simulation`` field so a refresh
    keeps the drill-down without re-running.
    """
    await verify_project_access(project_id, user_id, session)
    data = await service.simulate(
        project_id,
        iterations=body.iterations,
        mode=body.mode,
    )
    return RiskSimulationResult(**data)


# ── Risk-based contingency (EMV vs the finance contingency line) ─────────
#
# Project-scoped (``/projects/{project_id}/contingency...``) so the routes never
# collide with ``/{risk_id}``, and so a drawdown of a risk that was deleted
# later can still be found and reversed through its project.


@router.get(
    "/projects/{project_id}/contingency",
    response_model=ContingencyPosition,
    dependencies=[Depends(RequirePermission("risk.read"))],
)
async def get_contingency_position(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RiskService = Depends(_get_service),
) -> ContingencyPosition:
    """Risk-based contingency (EMV, P50/P80) against the finance contingency lines.

    Allocated contingency is the project's finance budget lines in the
    Contingency category; drawn is what people confirmed for risks that
    occurred; remaining is allocated minus drawn. Totals are in the project
    currency, converted with the project's FX table; an amount in a currency
    without a rate is reported apart instead of being summed in its own units.
    """
    await verify_project_access(project_id, user_id, session)
    return ContingencyPosition(**await service.get_contingency_position(project_id))


@router.post(
    "/projects/{project_id}/contingency/drawdowns/{risk_id}",
    response_model=ContingencyPosition,
    dependencies=[Depends(RequirePermission("risk.contingency"))],
)
async def confirm_contingency_drawdown(
    project_id: uuid.UUID,
    risk_id: uuid.UUID,
    body: ContingencyDrawdownRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RiskService = Depends(_get_service),
) -> ContingencyPosition:
    """Confirm the amount an occurred risk draws from a contingency line.

    One drawdown per risk: confirming again replaces it, and replaying the
    same confirmation changes nothing. The amount is in the currency of the
    chosen line. Returns the updated position.
    """
    await verify_project_access(project_id, user_id, session)
    data = await service.confirm_contingency_drawdown(
        project_id,
        risk_id,
        body,
        user_id=str(user_id) if user_id else None,
    )
    return ContingencyPosition(**data)


@router.delete(
    "/projects/{project_id}/contingency/drawdowns/{risk_id}",
    response_model=ContingencyPosition,
    dependencies=[Depends(RequirePermission("risk.contingency"))],
)
async def reverse_contingency_drawdown(
    project_id: uuid.UUID,
    risk_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RiskService = Depends(_get_service),
) -> ContingencyPosition:
    """Reverse a confirmed drawdown and return the updated position."""
    await verify_project_access(project_id, user_id, session)
    data = await service.reverse_contingency_drawdown(
        project_id,
        risk_id,
        user_id=str(user_id) if user_id else None,
    )
    return ContingencyPosition(**data)


# ── Auto-escalation sweep (TOP-30 #24) ───────────────────────────────────
#
# Manual, on-demand counterpart to the periodic sweep the central scheduler
# runs. Mounted under ``/projects/{project_id}/escalate`` (non-parametric
# prefix) so it does not collide with ``/{risk_id}``. Gated at
# ``risk.escalate`` (MANAGER) because escalation drives notifications and
# auto-creates action items - a supervisory action, not a routine edit.


@router.post(
    "/projects/{project_id}/escalate",
    response_model=RiskEscalationSweepResult,
    dependencies=[Depends(RequirePermission("risk.escalate"))],
)
async def escalate_project_risks(
    project_id: uuid.UUID,
    body: RiskEscalationSweepRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> RiskEscalationSweepResult:
    """Run an auto-escalation sweep over one project's risks.

    Escalates every not-yet-escalated risk whose severity product crosses
    the threshold or whose next-review date has lapsed. Idempotent - risks
    already escalated for their current trigger are skipped. Each escalation
    flips the flag, stamps ``escalated_at``, appends a mitigation action and
    emits ``risk.escalated``.
    """
    from app.modules.risk.escalation import (
        DEFAULT_ESCALATION_THRESHOLD,
        RiskEscalationService,
    )

    await verify_project_access(project_id, user_id, session)
    svc = RiskEscalationService(session)
    summary = await svc.sweep(
        project_id=project_id,
        default_threshold=body.threshold or DEFAULT_ESCALATION_THRESHOLD,
    )
    return RiskEscalationSweepResult(**summary)


# ── Bulk operations (must come BEFORE parametric /{risk_id}) ─────────


async def _authorized_risk_ids(
    session: SessionDep,
    user_id: str,
    requested_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Return the subset of ``requested_ids`` the caller may act on.

    Authorization mirrors every other risk route - ``verify_project_access``
    (owner **or** admin **or** project team member), not the bare
    owner-only filter the batch handlers previously used. We resolve each
    distinct project once, skip rows in projects the caller can't reach
    (verify_project_access raises 404 on denial), and keep the rest.
    """
    from sqlalchemy import select as _select

    from app.modules.risk.models import RiskItem

    rows = (
        await session.execute(_select(RiskItem.id, RiskItem.project_id).where(RiskItem.id.in_(requested_ids)))
    ).all()

    allowed_projects: dict[str, bool] = {}
    allowed_ids: list[uuid.UUID] = []
    for risk_id, project_id in rows:
        key = str(project_id)
        if key not in allowed_projects:
            try:
                await verify_project_access(project_id, user_id, session)
                allowed_projects[key] = True
            except HTTPException:
                allowed_projects[key] = False
        if allowed_projects[key]:
            allowed_ids.append(risk_id)
    return allowed_ids


@router.post(
    "/batch/delete/",
    status_code=200,
    dependencies=[Depends(RequirePermission("risk.delete"))],
)
async def batch_delete_risks(
    body: BulkDeleteRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Delete multiple risks in one request.

    Gated behind ``risk.delete`` (MANAGER) to match single-row delete, and
    authorized per-project via ``verify_project_access`` so admins and team
    members can bulk-delete the same rows they can delete individually.
    """
    from app.core.bulk_ops import bulk_delete
    from app.modules.risk.models import RiskItem

    allowed = await _authorized_risk_ids(session, str(user_id), body.ids)
    deleted = await bulk_delete(session, RiskItem, allowed)
    return {"requested": len(body.ids), "deleted": deleted}


@router.patch(
    "/batch/status/",
    status_code=200,
    dependencies=[Depends(RequirePermission("risk.update"))],
)
async def batch_update_risk_status(
    body: BulkStatusRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Bulk-update status on multiple risks.

    Gated behind ``risk.update`` (EDITOR) to match single-row status edit,
    and authorized per-project via ``verify_project_access``.
    """
    from app.core.bulk_ops import bulk_update_status
    from app.modules.risk.models import RiskItem
    from app.modules.risk.schemas import STATUS_VALUES

    # Canonical set lives in schemas.STATUS_VALUES - the previous hardcoded
    # subset silently rejected the "monitoring" and "mitigated" tiers that
    # seeded risks already use, leaving bulk-update broken for them.
    allowed_statuses = set(STATUS_VALUES)
    if body.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Allowed: {sorted(allowed_statuses)}",
        )

    allowed_ids = await _authorized_risk_ids(session, str(user_id), body.ids)
    updated = await bulk_update_status(session, RiskItem, allowed_ids, body.status, allowed_statuses=allowed_statuses)
    return {"requested": len(body.ids), "updated": updated, "status": body.status}


# ── Get ──────────────────────────────────────────────────────────────────────


@router.get(
    "/{risk_id}",
    response_model=RiskResponse,
    dependencies=[Depends(RequirePermission("risk.read"))],
)
async def get_risk(
    risk_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RiskService = Depends(_get_service),
) -> RiskResponse:
    """Get a single risk item."""
    item = await service.get_risk(risk_id)
    await verify_project_access(item.project_id, str(user_id), session)
    return _risk_to_response(item)


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch("/{risk_id}", response_model=RiskResponse)
async def update_risk(
    risk_id: uuid.UUID,
    data: RiskUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("risk.update")),
    service: RiskService = Depends(_get_service),
) -> RiskResponse:
    """Update a risk item."""
    existing = await service.get_risk(risk_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    item = await service.update_risk(risk_id, data, user_id=str(user_id) if user_id else None)
    return _risk_to_response(item)


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete("/{risk_id}", status_code=204)
async def delete_risk(
    risk_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("risk.delete")),
    service: RiskService = Depends(_get_service),
) -> None:
    """Delete a risk item."""
    existing = await service.get_risk(risk_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_risk(risk_id)


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# ``/vector/status/`` + ``/vector/reindex/`` wired via the shared factory
# (see the ``include_router`` call at the bottom of this file).  Risks
# are the single highest-value collection for cross-project semantic
# search - lessons learned reuse is why this infrastructure exists in
# the first place - so the ``similar`` endpoint below defaults to
# ``cross_project=true``.


@router.get(
    "/{risk_id}/similar/",
    dependencies=[Depends(RequirePermission("risk.read"))],
)
async def risk_similar(
    risk_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
    limit: int = Query(default=5, ge=1, le=20),
    cross_project: bool = Query(default=True),
) -> dict[str, Any]:
    """Return risks semantically similar to the given one.

    Defaults to **cross-project** search - this is the whole point of
    the risk vector collection.  Estimators starting a new project want
    to instantly surface "risks like this one that we already faced on
    past jobs" so they can reuse the mitigation strategy, contingency
    plan and budget reserve.  Pass ``cross_project=false`` to restrict
    the search to the same project (rarely the right choice for risks).

    Returns a list of :class:`VectorHit` dicts plus the source row id so
    the frontend can highlight the origin.
    """
    from sqlalchemy import select

    from app.core.vector_index import find_similar
    from app.dependencies import allowed_project_ids_for_similar
    from app.modules.risk.models import RiskItem
    from app.modules.risk.vector_adapter import risk_vector_adapter

    stmt = select(RiskItem).where(RiskItem.id == risk_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")

    if row.project_id is not None:
        await verify_project_access(row.project_id, str(_user_id), session)

    project_id = str(row.project_id) if row.project_id is not None else None
    # Cross-tenant guard: restrict cross-project hits to projects the caller
    # may access (None == admin/unrestricted, mirroring verify_project_access).
    allowed = await allowed_project_ids_for_similar(session, str(_user_id), project_id, cross_project)
    hits = await find_similar(
        risk_vector_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=limit,
        allowed_project_ids=allowed,
    )
    return {
        "source_id": str(risk_id),
        "limit": limit,
        "cross_project": cross_project,
        "hits": [h.to_dict() for h in hits],
    }


# ── Mount vector status + reindex via the shared factory ────────────────
from app.core.vector_index import COLLECTION_RISKS  # noqa: E402
from app.core.vector_routes import create_vector_routes  # noqa: E402
from app.modules.risk.models import RiskItem as _RiskItemModel  # noqa: E402
from app.modules.risk.vector_adapter import (  # noqa: E402
    risk_vector_adapter as _risk_vector_adapter,
)

router.include_router(
    create_vector_routes(
        collection=COLLECTION_RISKS,
        adapter=_risk_vector_adapter,
        model=_RiskItemModel,
        read_permission="risk.read",
        write_permission="risk.update",
        project_id_attr="project_id",
    )
)
