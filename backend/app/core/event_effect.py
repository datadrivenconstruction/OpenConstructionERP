# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Once-only guard for the side effect of an event.

The bus delivers at least once, so a subscriber that moves stock or money has
to be able to ask "did I already do this for this event?". ``claim_effect``
answers by inserting a row under a unique key: the first caller gets the row
and does the work, every later caller hits the unique index and skips.

The claim is written in the caller's transaction, so the effect and its claim
commit or roll back together.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EventEffect(Base):
    """One claimed side effect, identified by the publisher's idempotency key."""

    __tablename__ = "oe_event_effect"

    key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    effect: Mapped[str] = mapped_column(String(100), nullable=False, default="")


async def claim_effect(session: AsyncSession, key: str, effect: str = "") -> bool:
    """Claim ``key`` for this caller; ``False`` means someone already did the work."""
    try:
        async with session.begin_nested():
            session.add(EventEffect(key=key, effect=effect))
            await session.flush()
    except IntegrityError:
        return False
    return True
