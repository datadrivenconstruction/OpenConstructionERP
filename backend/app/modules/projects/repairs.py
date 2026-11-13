"""Boot-path data repairs owned by the projects module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _run_country_from_region(session: AsyncSession) -> int:
    """Imported inside the function so registering costs only the registration."""
    from app.modules.projects.country_backfill import backfill_country_from_region

    return await backfill_country_from_region(session)


#: Nature ``always_wrong``: a project with no country whose region names one was
#: priced with no national VAT default. Filling an empty country is the whole
#: repair; a country already set is never touched.
PROJECT_COUNTRY_FROM_REGION = register_data_repair(
    DataRepair(
        repair_id="project_country_from_region",
        revision="vpc01_project_country_from_region",
        summary="Set the country of projects with no country whose region names exactly one",
        run=_run_country_from_region,
        nature="always_wrong",
    )
)
