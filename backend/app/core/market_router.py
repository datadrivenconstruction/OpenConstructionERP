# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP surface of the market scope.

    GET /api/v1/market/                 - any signed-in user: the resolved scope.
    GET /api/v1/market/?project_id=...  - the same, narrowed to that project's country.
    PUT /api/v1/market/                 - package admins: save the market profile.

The profile lives in the tenant's metadata beside the solution package state,
so this needs no migration. See :mod:`app.core.market_scope`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import market_scope as ms
from app.core.module_guard import invalidate_user
from app.core.solution_packages_router import can_manage_packages, require_package_admin
from app.dependencies import CurrentUserId, SessionDep, get_current_user_payload
from app.modules.users.router import _get_service
from app.modules.users.service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["Market scope"])


class MarketEntry(BaseModel):
    """One market: ISO 3166-1 alpha-2 country and an optional ISO 3166-2 subdivision."""

    country: str = Field(min_length=2, max_length=2)
    subdivision: str = Field(default="", max_length=8)


class StandardsBody(BaseModel):
    """Standards the tenant works to; blank means the market default."""

    classification: str = ""
    measurement: str = ""
    contract_family: str = ""
    tax_profile: str = ""
    units: str = ""


class MarketProfileBody(BaseModel):
    """Admin payload for ``PUT /market/``."""

    primary: MarketEntry
    extra_markets: list[MarketEntry] = Field(default_factory=list, max_length=50)
    company_type: str | None = None
    standards: StandardsBody = Field(default_factory=StandardsBody)
    keep_modules: list[str] = Field(default_factory=list, max_length=200)


def _active_pack_country() -> str | None:
    try:
        from app.core.partner_pack.discovery import get_active_pack

        pack = get_active_pack()
    except Exception:  # noqa: BLE001 - a broken pack must not break the scope
        logger.debug("market: active pack lookup failed", exc_info=True)
        return None
    return (pack.metadata or {}).get("country") if pack else None


async def _project_countries(session: Any, owner_id: uuid.UUID) -> list[str]:
    from app.modules.projects.models import Project

    rows = await session.execute(select(Project.country_code).where(Project.owner_id == owner_id))
    return [c for (c,) in rows if c]


async def _payload(
    metadata: dict[str, Any], session: Any, owner_id: uuid.UUID, project_id: uuid.UUID | None
) -> dict[str, Any]:
    profile = ms.stored_profile(metadata)
    derived = profile is None
    if profile is None:
        profile = ms.derive_profile(
            metadata,
            project_countries=await _project_countries(session, owner_id),
            active_pack_country=_active_pack_country(),
        )
    project_country = None
    if project_id is not None:
        from app.modules.projects.models import Project

        project = await session.get(Project, project_id)
        if project is None or project.owner_id != owner_id:
            raise HTTPException(status_code=404, detail="Project not found")
        project_country = project.country_code
    return {"profile": profile, "derived": derived, **ms.resolve(profile, project_country=project_country)}


@router.get("/")
async def get_market_scope(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = None,
    payload: dict[str, Any] = Depends(get_current_user_payload),
    service: UserService = Depends(_get_service),
) -> dict[str, Any]:
    """The resolved market scope: markets, hidden modules, units, standards, rule sets."""
    user = await service.get_user(uuid.UUID(user_id))
    out = await _payload(dict(user.metadata_ or {}), session, uuid.UUID(user_id), project_id)
    return {**out, "can_edit": can_manage_packages(payload)}


@router.put("/", dependencies=[Depends(require_package_admin)])
async def put_market_profile(
    body: MarketProfileBody,
    user_id: CurrentUserId,
    session: SessionDep,
    service: UserService = Depends(_get_service),
) -> dict[str, Any]:
    """Save the market profile. Nothing is uninstalled and no data is touched."""
    user = await service.get_user(uuid.UUID(user_id))
    metadata = ms.save_profile(dict(user.metadata_ or {}), body.model_dump())
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    invalidate_user(user_id)
    out = await _payload(metadata, session, uuid.UUID(user_id), None)
    return {**out, "can_edit": True}
