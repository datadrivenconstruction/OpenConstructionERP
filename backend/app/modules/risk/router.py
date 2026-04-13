"""Risk Register API routes.

Endpoints:
    POST   /                       — Create risk item
    GET    /?project_id=X          — List for project (with filters)
    GET    /{id}                   — Get single risk
    PATCH  /{id}                   — Update risk
    DELETE /{id}                   — Delete risk
    GET    /matrix?project_id=X    — Risk matrix data (5x5 grid)
    GET    /summary?project_id=X   — Aggregated stats
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.bulk_ops import BulkDeleteRequest, BulkStatusRequest
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.risk.schemas import (
    RiskCreate,
    RiskMatrixCell,
    RiskMatrixResponse,
    RiskResponse,
    RiskSummary,
    RiskUpdate,
)
from app.modules.risk.service import RiskService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> RiskService:
    return RiskService(session)


def _risk_to_response(item: object) -> RiskResponse:
    """Build a RiskResponse from a RiskItem ORM object."""
    return RiskResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        code=item.code,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        category=item.category,  # type: ignore[attr-defined]
        probability=float(item.probability),  # type: ignore[attr-defined]
        impact_cost=float(item.impact_cost),  # type: ignore[attr-defined]
        impact_schedule_days=item.impact_schedule_days,  # type: ignore[attr-defined]
        impact_severity=item.impact_severity,  # type: ignore[attr-defined]
        risk_score=float(item.risk_score),  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        mitigation_strategy=item.mitigation_strategy,  # type: ignore[attr-defined]
        contingency_plan=item.contingency_plan,  # type: ignore[attr-defined]
        owner_name=item.owner_name,  # type: ignore[attr-defined]
        response_cost=float(item.response_cost),  # type: ignore[attr-defined]
        currency=item.currency,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get("/summary/", response_model=RiskSummary)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RiskService = Depends(_get_service),
) -> RiskSummary:
    """Aggregated risk stats for a project."""
    data = await service.get_summary(project_id)
    return RiskSummary(**data)


# ── Matrix ───────────────────────────────────────────────────────────────────


@router.get("/matrix/", response_model=RiskMatrixResponse)
async def get_matrix(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RiskService = Depends(_get_service),
) -> RiskMatrixResponse:
    """5x5 risk matrix data for a project."""
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
        item = await service.create_risk(data)
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


@router.get("/", response_model=list[RiskResponse])
async def list_risks(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    sort_by: str | None = Query(
        default=None, description="Sort field: risk_score, probability, created_at"
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    service: RiskService = Depends(_get_service),
) -> list[RiskResponse]:
    """List risk items for a project."""
    items, _ = await service.list_risks(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        category_filter=category,
        severity_filter=severity,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return [_risk_to_response(i) for i in items]


# ── Bulk operations (must come BEFORE parametric /{risk_id}) ─────────


@router.post(
    "/batch/delete/",
    status_code=200,
)
async def batch_delete_risks(
    body: BulkDeleteRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Delete multiple risks in one request."""
    from sqlalchemy import select as _select

    from app.core.bulk_ops import bulk_delete
    from app.modules.projects.repository import ProjectRepository
    from app.modules.risk.models import RiskItem

    proj_repo = ProjectRepository(session)
    owned_projects, _ = await proj_repo.list_for_user(
        owner_id=user_id, offset=0, limit=10000, exclude_archived=False
    )
    owned_project_ids = {str(p.id) for p in owned_projects}

    rows = (await session.execute(
        _select(RiskItem.id, RiskItem.project_id).where(RiskItem.id.in_(body.ids))
    )).all()
    allowed = [r[0] for r in rows if str(r[1]) in owned_project_ids]

    deleted = await bulk_delete(session, RiskItem, allowed)
    return {"requested": len(body.ids), "deleted": deleted}


@router.patch(
    "/batch/status/",
    status_code=200,
)
async def batch_update_risk_status(
    body: BulkStatusRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Bulk-update status on multiple risks."""
    from sqlalchemy import select as _select

    from app.core.bulk_ops import bulk_update_status
    from app.modules.projects.repository import ProjectRepository
    from app.modules.risk.models import RiskItem

    allowed_statuses = {"identified", "assessed", "mitigating", "closed", "occurred"}
    if body.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Allowed: {sorted(allowed_statuses)}",
        )

    proj_repo = ProjectRepository(session)
    owned_projects, _ = await proj_repo.list_for_user(
        owner_id=user_id, offset=0, limit=10000, exclude_archived=False
    )
    owned_project_ids = {str(p.id) for p in owned_projects}

    rows = (await session.execute(
        _select(RiskItem.id, RiskItem.project_id).where(RiskItem.id.in_(body.ids))
    )).all()
    allowed_ids = [r[0] for r in rows if str(r[1]) in owned_project_ids]

    updated = await bulk_update_status(
        session, RiskItem, allowed_ids, body.status, allowed_statuses=allowed_statuses
    )
    return {"requested": len(body.ids), "updated": updated, "status": body.status}


# ── Get ──────────────────────────────────────────────────────────────────────


@router.get("/{risk_id}", response_model=RiskResponse)
async def get_risk(
    risk_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RiskService = Depends(_get_service),
) -> RiskResponse:
    """Get a single risk item."""
    item = await service.get_risk(risk_id)
    return _risk_to_response(item)


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch("/{risk_id}", response_model=RiskResponse)
async def update_risk(
    risk_id: uuid.UUID,
    data: RiskUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("risk.update")),
    service: RiskService = Depends(_get_service),
) -> RiskResponse:
    """Update a risk item."""
    item = await service.update_risk(risk_id, data)
    return _risk_to_response(item)


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete("/{risk_id}", status_code=204)
async def delete_risk(
    risk_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("risk.delete")),
    service: RiskService = Depends(_get_service),
) -> None:
    """Delete a risk item."""
    await service.delete_risk(risk_id)


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# ``/vector/status/`` + ``/vector/reindex/`` wired via the shared factory
# (see the ``include_router`` call at the bottom of this file).  Risks
# are the single highest-value collection for cross-project semantic
# search — lessons learned reuse is why this infrastructure exists in
# the first place — so the ``similar`` endpoint below defaults to
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

    Defaults to **cross-project** search — this is the whole point of
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
    from app.modules.risk.models import RiskItem
    from app.modules.risk.vector_adapter import risk_vector_adapter

    stmt = select(RiskItem).where(RiskItem.id == risk_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")

    project_id = str(row.project_id) if row.project_id is not None else None
    hits = await find_similar(
        risk_vector_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=limit,
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
