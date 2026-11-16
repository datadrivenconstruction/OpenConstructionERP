# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The company's active markets, for backend lists that a country pack contributes to.

A pack is "active" for a user when the company market profile (stored or derived, see
:mod:`app.core.market_scope`) names one of the pack's countries. A profile that names no
market reads as ``["*"]`` and activates no pack: nothing country-specific shows until a
market is chosen.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import Depends

from app.core import market_scope as ms
from app.dependencies import CurrentUserId, SessionDep, get_current_user_payload
from app.modules.users.router import _get_service
from app.modules.users.service import UserService


def pack_active(markets: Iterable[str], pack_countries: Iterable[str]) -> bool:
    """Whether a pack covering ``pack_countries`` is active for ``markets``."""
    active = ms.expand_markets(markets)
    if ms.ALL_MARKETS in active:
        return False
    return bool(active & {str(c).strip().upper() for c in pack_countries})


async def resolve_active_markets(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    service: Annotated[UserService, Depends(_get_service)],
) -> list[str]:
    """Market codes of the caller's company profile, ``["*"]`` when none is set."""
    from app.core import market_router as mr

    _, metadata = await mr._company_metadata(service, session, payload, uuid.UUID(user_id))
    profile = ms.stored_profile(metadata)
    if profile is None:
        profile = ms.derive_profile(
            metadata,
            project_countries=await mr._project_countries(session, mr._tenant_owner(payload)),
            active_pack_country=mr._active_pack_country(),
        )
    return ms.profile_markets(profile)


ActiveMarkets = Annotated[list[str], Depends(resolve_active_markets)]
