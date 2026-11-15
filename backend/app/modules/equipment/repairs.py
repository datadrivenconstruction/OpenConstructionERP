# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the equipment module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_TABLE = "oe_equipment_equipment"


async def _run_tenant_backfill(session: AsyncSession) -> int:
    """Give units created before tenant scoping the install owner's tenant, then require it.

    The boot heal adds ``tenant_id`` nullable. Rows get the default tenant
    (see ``veq01_equipment_tenant``) and the column becomes NOT NULL.
    """
    from app.modules.equipment.tenancy import default_tenant_id

    state = await session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t AND column_name = 'tenant_id'"
        ),
        {"t": _TABLE},
    )
    row = state.first()
    if row is None:
        return 0
    rewritten = 0
    if row[0] == "YES":
        result = await session.execute(
            text(f"UPDATE {_TABLE} SET tenant_id = :tenant WHERE tenant_id IS NULL"),  # noqa: S608
            {"tenant": await default_tenant_id(session)},
        )
        rewritten = result.rowcount or 0
        await session.execute(text(f"ALTER TABLE {_TABLE} ALTER COLUMN tenant_id SET NOT NULL"))  # noqa: S608
    return rewritten


#: ``always_wrong``: a unit with no owner has never been a valid state of the
#: models, which declare the column NOT NULL.
EQUIPMENT_TENANT_BACKFILL = register_data_repair(
    DataRepair(
        repair_id="equipment_tenant_backfill",
        revision="veq01_equipment_tenant",
        summary="Assign the install owner's tenant to fleet units that predate tenant scoping and require it",
        run=_run_tenant_backfill,
        nature="always_wrong",
    )
)
