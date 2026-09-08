# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Review routes for resource buildups that cannot price their position.

Included into the BOQ ``router`` via ``router.include_router`` so the routes
mount under ``/api/v1/boq``:

    GET  /projects/{project_id}/resource-norm-review    - list flagged positions
    POST /positions/{position_id}/resource-norm-review  - re-derive one, or mark it

The listing is read-only. The POST rewrites the resource rows of ONE position
from its linked catalogue item, and only after the caller repeats the request
with ``confirm`` set; a position without a usable link is marked for review
and left as it is. Neither route touches ``unit_rate`` or ``total``. The
platform rule that AI results are never applied without a person confirming
them is what shapes this surface: nothing here runs over a whole project.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.boq.repository import PositionRepository
from app.modules.boq.resource_review import ResourceNormReviewService

resource_review_router = APIRouter(tags=["boq"])


class ResourceNormReviewRequest(BaseModel):
    """Body of the per-position review call."""

    confirm: bool = Field(
        default=False,
        description=(
            "Set to true to let the call replace the position's resource rows with the "
            "catalogue's per-unit norms. Without it a recoverable position is refused with 422 "
            "and nothing is written. Positions without a catalogue link are marked either way."
        ),
    )


class ResourceNormReviewPosition(BaseModel):
    """One flagged position as the listing reports it."""

    position_id: str
    boq_id: str
    boq_name: str
    ordinal: str
    description: str
    unit: str
    quantity: str
    unit_rate: str
    resource_subtotal: str
    category: str
    recoverable: bool
    cost_item_id: str | None = None
    row_count: int
    flagged_rows: int
    unit_rate_kept_on_edit: dict[str, Any] | None = None
    review_reason: str | None = None
    reviewed: dict[str, Any] | None = None
    created_at: str | None = None


class ResourceNormReviewReport(BaseModel):
    """The project-level listing."""

    project_id: str
    boq_count: int
    positions_scanned: int
    positions_flagged: int
    recoverable: int
    review_only: int
    counts: dict[str, int]
    positions: list[ResourceNormReviewPosition]


class ResourceNormReviewResult(BaseModel):
    """What the per-position call did."""

    action: str
    position_id: str
    category: str
    unit_rate: str
    total: str
    rows_before: int
    rows_after: int
    review_reason: str | None = None
    resource_subtotal_before: str | None = None
    resource_subtotal_after: str | None = None
    resources: list[dict[str, Any]] | None = None


@resource_review_router.get(
    "/projects/{project_id}/resource-norm-review",
    response_model=ResourceNormReviewReport,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_resource_norm_review(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ResourceNormReviewReport:
    """List the project's positions whose resource rows cannot price the line.

    Per category counts plus one entry per position: the shape found, the
    stored rate against the sum the rows would have written over it, whether a
    catalogue link makes the rows recoverable, and whether an edit already had
    to keep the rate.
    """
    await verify_project_access(project_id, user_id, session)
    report = await ResourceNormReviewService(session).list_for_project(project_id)
    return ResourceNormReviewReport.model_validate(report)


@resource_review_router.post(
    "/positions/{position_id}/resource-norm-review",
    response_model=ResourceNormReviewResult,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def review_position_resource_norms(
    position_id: uuid.UUID,
    body: ResourceNormReviewRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ResourceNormReviewResult:
    """Re-derive one position's rows from its catalogue item, or mark it for review.

    Recoverable positions (a ``cost_item_id`` whose catalogue row carries
    components) are rewritten to per-unit norms only when ``confirm`` is true;
    the previous rows stay on the position under ``metadata.resource_norm_review``.
    Positions without a usable link get ``metadata.review_reason`` and nothing
    else changes. Money is never touched.
    """
    repo = PositionRepository(session)
    position = await repo.get_by_id(position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    project_id = await repo.project_id_for_boq(position.boq_id)
    if project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    await verify_project_access(project_id, user_id, session)

    try:
        actor_id: uuid.UUID | None = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        actor_id = None
    result = await ResourceNormReviewService(session).review_position(
        position_id,
        confirm=body.confirm,
        actor_id=actor_id,
    )
    return ResourceNormReviewResult.model_validate(result)
