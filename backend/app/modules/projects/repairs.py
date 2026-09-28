# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the projects module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_TABLE = "oe_projects_project"
_COLUMN = "unit_system"

#: What ``v3135_project_unit_system`` gave the column as its server default.
_CHAIN_DEFAULT = "metric"


async def clear_chain_unit_system_default(session: AsyncSession) -> int:
    """Clear the ``'metric'`` the v3135 default wrote, and drop that default.

    Only a database that walked the migration chain has the column with that
    default; one built by ``create_all`` got it from the model, nullable and
    with no default, and is left untouched. The boot heal has already relaxed
    the chain's NOT NULL by the time this runs, since the model declares the
    column optional.

    The live default is the gate. It is dropped in the same transaction as the
    values are cleared, so the repair acts once: after that, a ``metric`` in
    the column is a choice somebody made in the project settings and the next
    boot does not touch it.

    Returns:
        The number of projects whose unit system was cleared.
    """
    if session.get_bind().dialect.name != "postgresql":
        return 0
    default = (
        await session.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :table AND column_name = :column"
            ),
            {"table": _TABLE, "column": _COLUMN},
        )
    ).scalar_one_or_none()
    if _CHAIN_DEFAULT not in str(default or ""):
        return 0
    await session.execute(text(f'ALTER TABLE "{_TABLE}" ALTER COLUMN "{_COLUMN}" DROP NOT NULL'))
    await session.execute(text(f'ALTER TABLE "{_TABLE}" ALTER COLUMN "{_COLUMN}" DROP DEFAULT'))
    result = await session.execute(
        text(f'UPDATE "{_TABLE}" SET "{_COLUMN}" = NULL WHERE "{_COLUMN}" = :chain'),
        {"chain": _CHAIN_DEFAULT},
    )
    return int(result.rowcount or 0)


#: Nature ``always_wrong``: the chain's default stamped ``metric`` on projects
#: nobody had asked, while no API, screen or import could write the column.
#: There is no date on which it was a statement about a project, so clearing it
#: in place is the whole repair - and leaving it would make every such United
#: States project explicitly metric and warn on its imperial bills.
PROJECT_UNIT_SYSTEM_CHAIN_DEFAULT = register_data_repair(
    DataRepair(
        repair_id="project_unit_system_chain_default",
        revision="v48_project_jurisdiction_unit_system",
        summary="Clear the metric unit system the v3135 column default stamped on every project",
        run=clear_chain_unit_system_default,
        nature="always_wrong",
    )
)
