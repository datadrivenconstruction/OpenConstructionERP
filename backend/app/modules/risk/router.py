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

from fastapi import APIRouter, Depends, HTTPException, Query, status

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


@router.get("/summary", response_model=RiskSummary)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RiskService = Depends(_get_service),
) -> RiskSummary:
    """Aggregated risk stats for a project."""
    data = await service.get_summary(project_id)
    return RiskSummary(**data)


# ── Matrix ───────────────────────────────────────────────────────────────────


@router.get("/matrix", response_model=RiskMatrixResponse)
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
    )
    return [_risk_to_response(i) for i in items]


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
