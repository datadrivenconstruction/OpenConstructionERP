# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register event handlers.

Subscribed:
    contracts.claim.certified  -> reduce the contract's advance payment guarantees.
    tendering.package.awarded  -> release the losing bidders' bid bonds.

Published by the service (after commit): ``guarantees.guarantee.created``,
``.updated``, ``.status_changed``, ``.reduced`` and ``.expiring``.

Both publishers emit after their commit, so each handler opens its own session
and reads committed rows. A failure is logged and never reaches the publisher.
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _on_claim_certified(event: Event) -> None:
    claim_id = _uuid((event.data or {}).get("claim_id"))
    if claim_id is None:
        return
    from app.database import async_session_factory
    from app.modules.guarantees.service import GuaranteesService

    try:
        async with async_session_factory() as session:
            touched = await GuaranteesService(session).apply_certified_claim(claim_id)
            await session.commit()
        if touched:
            logger.info("Advance guarantees reduced after claim %s: %d", claim_id, touched)
    except Exception:  # noqa: BLE001 - a subscriber never breaks the certificate
        logger.warning("advance guarantee reduction failed for claim %s", claim_id, exc_info=True)


async def _on_tender_awarded(event: Event) -> None:
    data = event.data or {}
    package_id = _uuid(data.get("package_id"))
    if package_id is None:
        return
    from app.database import async_session_factory
    from app.modules.guarantees.service import GuaranteesService

    try:
        async with async_session_factory() as session:
            await GuaranteesService(session).release_bid_bonds_for_award(package_id, _uuid(data.get("bid_id")))
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("bid bond release failed for package %s", package_id, exc_info=True)


def register_guarantees_subscriptions() -> None:
    """Subscribe the handlers once (idempotent across reloads)."""
    event_bus.subscribe_once("contracts.claim.certified", _on_claim_certified)
    event_bus.subscribe_once("tendering.package.awarded", _on_tender_awarded)
