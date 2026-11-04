# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boolean front for the run-once ledger in :mod:`app.core.event_effects`.

Both entry points write the one ``oe_event_effect`` table; this one answers
"did I already do this?" with a bool for subscribers that keep no claim row.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_effects import EventEffect
from app.core.event_effects import claim_effect as _claim

__all__ = ["EventEffect", "claim_effect"]


async def claim_effect(session: AsyncSession, key: str, effect: str = "") -> bool:
    """Claim ``key`` for this caller; ``False`` means someone already did the work."""
    return await _claim(session, key, effect) is not None
