# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Riverside Yard survey demo: the course's data, loaded into one project.

Seeds the project CRS, the control and existing-ground point sets, the demo
profile (labelled as demo values, not a standard), the closed traverse, the two
surfaces and the draft volume V-001. Confirming and sending stay for the
learner: the computer suggests, the person confirms.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
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
        SurveyProfileIn(label=DEMO_PROFILE_LABEL, traverse_min_ratio=10000, coverage_min_pct=90, control_tol_mm=20),
        user_id,
        source="demo",
    )
    control = await core.import_points(
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
    await _seed_control_checks(session, project_id, control.point_set.id, user_id)
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
    pages = await _seed_site_pages(session, project_id, user_id)
    pay = await _seed_pay(session, project_id, user_id, calc.id)
    return {
        **piles,
        **mine,
        **pages,
        **pay,
        "survey_points": ground.imported + 4,
        "survey_surfaces": 2,
        "survey_volumes": 1,
        "survey_cut_m3": calc.cut_m3,
    }


async def _seed_pay(session: AsyncSession, project_id: uuid.UUID, user_id: str, volume_id: uuid.UUID) -> dict[str, Any]:
    """Subcontract, open certificate and haul tickets; a slim install without them keeps the survey data."""
    from app.modules.surfaces_volumes.demo_pay import seed_pay_demo

    try:
        async with session.begin_nested():
            return await seed_pay_demo(session, project_id, user_id, volume_id)
    except Exception:  # noqa: BLE001 - a missing optional module drops only the payment part
        logger.warning("Riverside Yard payment demo not seeded", exc_info=True)
        return {}


#: Morning check shots on the control: CP1 within the demo 20 mm, CP3 off by 29.5 mm (SRV-012).
DEMO_CHECKS = {"CP1": (0.006, -0.004, 0.003), "CP3": (0.027, 0.012, -0.008)}


async def _seed_control_checks(session: AsyncSession, project_id: uuid.UUID, set_id: uuid.UUID, user_id: str) -> None:
    from sqlalchemy import select

    from app.modules.survey_core.models import SurveyPoint
    from app.modules.survey_core.register_schemas import ControlCheckIn
    from app.modules.survey_core.register_service import RegisterService

    rows = (await session.execute(select(SurveyPoint).where(SurveyPoint.point_set_id == set_id))).scalars().all()
    register = RegisterService(session)
    for p in rows:
        if p.point_id not in DEMO_CHECKS:
            continue
        de, dn, dz = DEMO_CHECKS[p.point_id]
        await register.add_check(
            project_id,
            ControlCheckIn(
                control_point_id=p.id,
                e=float(p.e) + de,
                n=float(p.n) + dn,
                z=float(p.z) + dz if p.z is not None else None,
                note="Morning check shot",
            ),
            user_id,
        )


async def _seed_site_pages(session: AsyncSession, project_id: uuid.UUID, user_id: str) -> dict[str, Any]:
    """Setting-out, monitoring (three epochs) and parcels, so every survey page of the demo has data."""
    from app.modules.land_parcels.schemas import ImportRequest as ParcelImport
    from app.modules.land_parcels.service import ParcelService
    from app.modules.monitoring.service import MonitoringService
    from app.modules.setting_out.service import SettingOutService

    parcels_dir = Path(__file__).resolve().parents[1] / "land_parcels" / "demo" / "riverside"
    request = await SettingOutService(session).load_riverside_demo(project_id, user_id)
    monitoring = MonitoringService(session)
    points = await monitoring.load_riverside_demo(project_id, user_id, [], "en", epochs=3)
    points = await _seed_alarm_point(monitoring, project_id, user_id) or points
    parcels = ParcelService(session)
    imported = await parcels.import_file(
        project_id,
        ParcelImport(
            format="geojson",
            target="parcels",
            filename="parcels.geojson",
            text=(parcels_dir / "parcels.geojson").read_text(encoding="utf-8"),
        ),
        user_id,
        [],
    )
    await parcels.import_file(
        project_id,
        ParcelImport(
            format="geojson",
            target="work_zone",
            filename="work_zone.geojson",
            text=(parcels_dir / "work_zone.geojson").read_text(encoding="utf-8"),
        ),
        user_id,
        [],
    )
    # P-004's register area is 950 m2 against 900 m2 by coordinates, so PAR-001 shows on the demo.
    mismatch = await parcels.import_file(
        project_id,
        ParcelImport(
            format="geojson",
            target="parcels",
            filename="parcel_p004.geojson",
            text=(parcels_dir / "parcel_p004.geojson").read_text(encoding="utf-8"),
        ),
        user_id,
        [],
    )
    return {
        "setting_out_requests": 1 if request else 0,
        "monitoring_points": len(points),
        "parcels": imported.created + mismatch.created,
    }


async def _seed_alarm_point(monitoring: Any, project_id: uuid.UUID, user_id: str) -> list[Any]:
    """MP-03 settles 34 mm in two weeks: past the demo alarm level, so MON-001 shows red on the demo."""
    from app.modules.monitoring.schemas import PointCreate, ReadingsImport

    demo_dir = Path(__file__).resolve().parents[1] / "monitoring" / "demo" / "riverside"
    if "MP-03" not in {p.code for p in await monitoring.repo.list_points(project_id)}:
        await monitoring.create_point(
            project_id,
            PointCreate(code="MP-03", name="Pit wall pin 3", point_type="settlement_pin", location="Pit-edge wall"),
            user_id,
        )
    await monitoring.import_readings(
        project_id,
        ReadingsImport(
            text=(demo_dir / "monitoring_mp03.csv").read_text(encoding="utf-8"), filename="monitoring_mp03.csv"
        ),
        user_id,
        [],
        "en",
    )
    return await monitoring.list_points(project_id, [])
