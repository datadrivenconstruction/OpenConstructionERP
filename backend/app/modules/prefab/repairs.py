# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the prefab module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def issue_missing_qr_tokens(session: AsyncSession) -> int:
    """Give every unit without a QR token one, so its label can be printed and scanned.

    Idempotent: a unit that already carries a token is never touched.
    """
    from sqlalchemy import select, update

    from app.modules.prefab.models import PrefabUnit

    ids = (await session.execute(select(PrefabUnit.id).where(PrefabUnit.qr_token.is_(None)))).scalars().all()
    for unit_id in ids:
        await session.execute(
            update(PrefabUnit).where(PrefabUnit.id == unit_id).values(qr_token=secrets.token_urlsafe(18))
        )
    return len(ids)


#: Nature ``always_wrong``: a unit created before v3332 has no token, and a unit
#: without one cannot be received by QR at all, so issuing one corrects a value
#: that was never usable. The column is added by the boot heal; this fills it.
PREFAB_UNIT_QR_TOKEN = register_data_repair(
    DataRepair(
        repair_id="prefab_unit_qr_token",
        revision="v3332_prefab_supply_chain_tracking",
        summary="Issue a QR token to every off-site unit that has none",
        run=issue_missing_qr_tokens,
        nature="always_wrong",
    )
)
