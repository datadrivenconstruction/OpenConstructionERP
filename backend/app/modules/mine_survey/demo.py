# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Riverside Yard mine survey demo: the October period with its plan and the two pit surfaces.

The learner computes the actual from the two surfaces, imports the truck loads
and adds the confirmed volume to the claim. The band and the truck check are
labelled as demo values, not a standard.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

DATA = Path(__file__).resolve().parent.parent / "survey_core" / "demo" / "riverside"
PERIOD = "2026-10"
DEMO_PROFILE_LABEL = "Demo values, not a standard"
BAND = (95.0, 105.0)
TRUCK_CHECK_PCT = 3.0


async def seed_mine_demo(session: AsyncSession, project_id: uuid.UUID, user_id: str) -> dict[str, Any]:
    """Create the October period, its plan line and the two pit surfaces in ``project_id``."""
    from app.modules.mine_survey.schemas import PeriodCreate, PlanImport
    from app.modules.mine_survey.service import MineService

    svc = MineService(session)
    created = await svc.create_period(
        project_id,
        PeriodCreate(
            label=PERIOD,
            band_lo_pct=BAND[0],
            band_hi_pct=BAND[1],
            truck_tolerance_pct=TRUCK_CHECK_PCT,
            profile_label=DEMO_PROFILE_LABEL,
        ),
        user_id,
    )
    plan = await svc.import_plan(
        await svc.get_period(created.id),
        PlanImport(text=(DATA / "pit_plan_2026-10.csv").read_text(encoding="utf-8"), filename="pit_plan_2026-10.csv"),
        user_id,
    )
    for name, filename in (("Pit N 2026-10-01", "pit_2026-10-01.csv"), ("Pit N 2026-10-31", "pit_2026-10-31.csv")):
        await svc._surface_from_text(project_id, (DATA / filename).read_text(encoding="utf-8"), filename, name, user_id)
    return {"mine_periods": 1, "mine_plan_lines": plan.imported}
