# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Suggested supplier routes for a BOQ position (issue #516).

Included into the BOQ ``router`` via ``router.include_router`` so the routes
mount under ``/api/v1/boq``:

    GET /positions/{position_id}/suggested-supplier  - the default and each material's suggestion
    PUT /positions/{position_id}/suggested-supplier  - set or clear one suggestion

Both check access to the position's project. The PUT writes only the
suggestion and never touches quantities, rates or totals.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.boq.models import Position
from app.modules.boq.repository import PositionRepository
from app.modules.boq.supplier_suggestion import SupplierSuggestionService

logger = logging.getLogger(__name__)

supplier_suggestion_router = APIRouter(tags=["boq"])


class SuggestedSupplierUpdate(BaseModel):
    """Set or clear one suggestion. Without ``resource_key`` the position default is set."""

    model_config = ConfigDict(str_strip_whitespace=True)

    vendor_id: uuid.UUID | None = None
    resource_key: str | None = Field(default=None, max_length=200)


class SuggestedSupplierResource(BaseModel):
    """One material resource of the position and its suggestion."""

    resource_key: str
    name: str
    code: str | None = None
    unit: str | None = None
    # The resource's own suggestion; null when it falls back to the default.
    suggested_vendor_id: uuid.UUID | None = None
    effective_vendor_id: uuid.UUID | None = None
    effective_vendor_name: str | None = None
    effective_vendor_status: str | None = None
    origin: str | None = None


class SuggestedSupplierResponse(BaseModel):
    """The position default and every material resource's suggestion."""

    position_id: uuid.UUID
    default_vendor_id: uuid.UUID | None = None
    default_vendor_name: str | None = None
    default_vendor_status: str | None = None
    resources: list[SuggestedSupplierResource] = Field(default_factory=list)


async def _position_with_access(position_id: uuid.UUID, user_id: str, session: Any) -> Position:
    repo = PositionRepository(session)
    position = await repo.get_by_id(position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    project_id = await repo.project_id_for_boq(position.boq_id)
    if project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    await verify_project_access(project_id, user_id, session)
    return position


@supplier_suggestion_router.get(
    "/positions/{position_id}/suggested-supplier",
    response_model=SuggestedSupplierResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_suggested_supplier(
    position_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SuggestedSupplierResponse:
    """The position's default suggested supplier and each material resource's own."""
    position = await _position_with_access(position_id, user_id, session)
    return SuggestedSupplierResponse.model_validate(await SupplierSuggestionService(session).describe(position))


@supplier_suggestion_router.put(
    "/positions/{position_id}/suggested-supplier",
    response_model=SuggestedSupplierResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def set_suggested_supplier(
    position_id: uuid.UUID,
    body: SuggestedSupplierUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SuggestedSupplierResponse:
    """Set or clear the suggested supplier of the position or of one material resource.

    A vendor must be in the Vendor directory (422 otherwise); a resource key
    that names no material resource of the position is a 404.
    """
    position = await _position_with_access(position_id, user_id, session)
    service = SupplierSuggestionService(session)
    changed = await service.set_suggestion(position, vendor_id=body.vendor_id, resource_key=body.resource_key)
    if changed:
        await session.flush()
        try:
            from app.core.audit_log import log_activity  # noqa: PLC0415

            await log_activity(
                session,
                actor_id=user_id,
                entity_type="boq_position",
                entity_id=str(position.id),
                action="suggested_supplier_changed",
                metadata={
                    "resource_key": body.resource_key,
                    "vendor_id": str(body.vendor_id) if body.vendor_id else None,
                },
            )
        except Exception:
            # Best effort like the other audit rows: logged loudly, the change stands.
            logger.warning("Activity log FAILED for suggested supplier on position %s", position.id, exc_info=True)
    return SuggestedSupplierResponse.model_validate(await service.describe(position))
