# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan print routes, included by the survey register router (same prefix and permissions).

Endpoints:
    POST /projects/{project_id}/plan.dxf          - the plan as DXF in grid metres, a layer per plan layer
    GET  /projects/{project_id}/plan-title-block  - company header, project, CRS, paper and convergence
"""

from __future__ import annotations

import base64
import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.active_markets import ActiveMarkets
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    get_current_user_payload,
    verify_project_access,
)
from app.modules.survey_core.plan_export import (
    PAPERS,
    SCALES,
    default_paper,
    grid_convergence_deg,
    parse_layers,
    to_plan_dxf,
)

router = APIRouter(tags=["survey_core"])

_READ = [Depends(RequirePermission("survey.read"))]
Payload = Annotated[dict[str, Any], Depends(get_current_user_payload)]


class PlanFeatureIn(BaseModel):
    kind: str = Field(pattern="^(point|line|polygon|text)$")
    coords: list[list[float]] = Field(min_length=1, max_length=20000)
    label: str = Field("", max_length=200)
    text_mm: float = Field(2.0, ge=0.5, le=20)


class PlanLayerIn(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    aci: int = Field(7, ge=1, le=255)
    features: list[PlanFeatureIn] = Field(default_factory=list, max_length=50000)


class PlanDxfIn(BaseModel):
    """The visible plan layers in grid coordinates, as the editor holds them."""

    title: str = Field("", max_length=200)
    drawing_no: str = Field("", max_length=60)
    revision: str = Field("", max_length=20)
    scale: int = Field(500, ge=1, le=100000)
    layers: list[PlanLayerIn] = Field(min_length=1, max_length=40)


class CompanyHeader(BaseModel):
    legal_name: str = ""
    address: str = ""
    registration_line: str = ""
    #: A PNG or JPEG data URL the PDF can place; "" when there is no logo.
    logo_data_url: str = ""


class TitleBlockOut(BaseModel):
    company: CompanyHeader
    project_name: str = ""
    project_code: str = ""
    epsg: int | None = None
    crs_name: str = ""
    is_local_grid: bool = False
    author: str = ""
    date: str
    paper: str
    papers: list[str]
    scales: list[int]
    #: Angle from grid north to true north at the plan centre, degrees; None without a CRS.
    convergence_deg: float | None = None


def _filename(text: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:60]
    return f"{stem or 'plan'}.dxf"


@router.post("/projects/{project_id}/plan.dxf", dependencies=_READ, response_class=Response)
async def plan_dxf(project_id: uuid.UUID, body: PlanDxfIn, session: SessionDep, user_id: CurrentUserId) -> Response:
    """The plan the user sees, as DXF in grid metres: one DXF layer per plan layer."""
    await verify_project_access(project_id, user_id, session)
    layers = parse_layers([layer.model_dump() for layer in body.layers])
    title = [body.title, " ".join(x for x in (body.drawing_no, body.revision) if x), f"1:{body.scale}"]
    data = to_plan_dxf(layers, body.scale, [t for t in title if t])
    return Response(
        content=data,
        media_type="application/dxf",
        headers={"Content-Disposition": f'attachment; filename="{_filename(body.drawing_no or body.title)}"'},
    )


async def _company(session: Any, project_id: uuid.UUID) -> CompanyHeader:
    """The issuing company: the project's legal entity laid over the company profile, as every PDF report does."""
    from app.core.company_profile import issuing_company, read_company_profile  # noqa: PLC0415
    from app.core.pdf_branding import branded_logo_bytes  # noqa: PLC0415

    entity = None
    try:
        from app.modules.legal_entities.seller import entity_for_contract, entity_profile  # noqa: PLC0415

        entity = await entity_for_contract(session, SimpleNamespace(project_id=project_id, metadata_={}))
        fields = entity_profile(entity) if entity is not None else None
    except ImportError:
        fields = None
    with issuing_company(fields):
        profile = read_company_profile()
        logo = branded_logo_bytes()
    logo_url = ""
    if logo:
        kind = "jpeg" if logo[:3] == b"\xff\xd8\xff" else "png"
        logo_url = f"data:image/{kind};base64,{base64.b64encode(logo).decode('ascii')}"
    return CompanyHeader(
        legal_name=profile.get("legal_name", ""),
        address=profile.get("address", ""),
        registration_line=profile.get("registration_line", ""),
        logo_data_url=logo_url,
    )


@router.get("/projects/{project_id}/plan-title-block", response_model=TitleBlockOut, dependencies=_READ)
async def plan_title_block(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    payload: Payload,
    e: float | None = Query(None),
    n: float | None = Query(None),
) -> TitleBlockOut:
    """Everything the printed plan's title block needs that the browser does not already hold."""
    await verify_project_access(project_id, user_id, session)
    from app.core.register_context import load_project_header  # noqa: PLC0415
    from app.modules.survey_core.crs import describe  # noqa: PLC0415
    from app.modules.survey_core.models import SurveyProjectCrs  # noqa: PLC0415

    project = await load_project_header(session, project_id)
    row = (
        await session.execute(
            select(SurveyProjectCrs.horizontal_epsg, SurveyProjectCrs.horizontal_name, SurveyProjectCrs.is_local_grid)
            .where(SurveyProjectCrs.project_id == project_id)
        )
    ).first()  # fmt: skip
    epsg = row[0] if row else None
    name = (row[1] if row else "") or ""
    if epsg and not name:
        try:
            name = describe(epsg).name
        except ValueError:
            name = ""
    convergence = grid_convergence_deg(epsg, e, n) if epsg and e is not None and n is not None else None
    return TitleBlockOut(
        company=await _company(session, project_id),
        project_name=project.name,
        project_code=project.code or "",
        epsg=epsg,
        crs_name=name,
        is_local_grid=bool(row[2]) if row else False,
        author=str(payload.get("full_name") or payload.get("email") or ""),
        date=datetime.now(UTC).date().isoformat(),
        paper=default_paper(markets, project.country),
        papers=list(PAPERS),
        scales=list(SCALES),
        convergence_deg=round(convergence, 6) if convergence is not None else None,
    )
