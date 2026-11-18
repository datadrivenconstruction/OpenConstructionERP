# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Riverside Yard survey demo: the course's data, loaded into one project.

Seeds the project CRS, the control and existing-ground point sets, the demo
profile (labelled as demo values, not a standard), the closed traverse, the two
surfaces and the draft volume V-001. Confirming and sending stay for the
learner: the computer suggests, the person confirms.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

DATA = Path(__file__).resolve().parent.parent / "survey_core" / "demo" / "riverside"
#: Demo templates whose install also seeds the survey course data.
SURVEY_DEMOS = frozenset({"survey-riverside-yard"})
DEMO_PROFILE_LABEL = "Demo values, not a standard"


async def seed_survey_demo(session: AsyncSession, project_id: uuid.UUID, user_id: str) -> dict[str, Any]:
    """Load the Riverside Yard survey data into ``project_id``; returns counts for the install summary."""
    from app.modules.surfaces_volumes.schemas import LandXmlImport, SurfaceFromPoints, VolumeCreate
    from app.modules.surfaces_volumes.service import VolumesService
    from app.modules.survey_core.schemas import ImportRequest, ProjectCrsSet, SurveyProfileIn, TraverseCreate
    from app.modules.survey_core.service import SurveyService

    core = SurveyService(session)
    await core.set_crs(project_id, ProjectCrsSet(horizontal_epsg=32633), user_id, True)
    await core.set_profile(
        project_id,
        SurveyProfileIn(label=DEMO_PROFILE_LABEL, traverse_min_ratio=10000, coverage_min_pct=90),
        user_id,
        source="demo",
    )
    await core.import_points(
        project_id,
        ImportRequest(
            text=(DATA / "control.csv").read_text(encoding="utf-8"),
            filename="control.csv",
            column_preset="PNEZD",
            default_kind="control",
            name="Control",
        ),
        user_id,
    )
    ground = await core.import_points(
        project_id,
        ImportRequest(
            text=(DATA / "existing_ground.csv").read_text(encoding="utf-8"),
            filename="existing_ground.csv",
            column_preset="PNEZD",
            default_kind="topo",
            name="Existing ground",
            duplicate_policy="keep_first",
        ),
        user_id,
    )
    await core.create_traverse(
        project_id,
        TraverseCreate(
            name="Site control loop", kind="traverse", text=(DATA / "traverse_legs.csv").read_text(encoding="utf-8")
        ),
        user_id,
    )
    volumes = VolumesService(session)
    existing = await volumes.surface_from_points(
        project_id, SurfaceFromPoints(name="Existing ground", point_set_ids=[ground.point_set.id]), user_id
    )
    design = await volumes.import_landxml(
        project_id,
        LandXmlImport(
            text=(DATA / "design_pad.xml").read_text(encoding="utf-8"), filename="design_pad.xml", name="Pad"
        ),
        user_id,
    )
    calc = await volumes.create_volume(
        project_id,
        VolumeCreate(
            name="Platform earthworks",
            base_surface_id=existing.id,
            compare_surface_id=design.surfaces[0].id,
        ),
        user_id,
    )
    from app.modules.mine_survey.demo import seed_mine_demo
    from app.modules.stockpiles.demo import seed_stockpile_demo

    piles = await seed_stockpile_demo(session, project_id, user_id)
    mine = await seed_mine_demo(session, project_id, user_id)
    return {
        **piles,
        **mine,
        "survey_points": ground.imported + 4,
        "survey_surfaces": 2,
        "survey_volumes": 1,
        "survey_cut_m3": calc.cut_m3,
    }
