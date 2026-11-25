"""/api/v1/design project start: the templates a new project can begin from.

A template is a generator typology (editor spec.rs/limits.rs, see ``model_params``). Picking one proposes the
values below; nothing is written here. The person sees them on the one summary screen with the other proposals,
corrects what is needed and confirms them all; only then do they become brief values.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import SessionDep

from . import quick
from .auth import PrincipalDep, require_project
from .model_params import CATEGORY, GENERATOR_REF, TYPOLOGY

# (id, brief use category); the generator typology follows from the category (model_params.CATEGORY)
TEMPLATES = (
    ("residential_block", "residential_multi"),
    ("house", "residential_single"),
    ("school", "school"),
    ("kindergarten", "kindergarten"),
    ("office", "office"),
)


def templates() -> list[dict[str, Any]]:
    """Each template with the values it proposes. A generator default is marked doubtful: it is typical, not known
    for this project, so the summary screen highlights it for the person to check."""
    out = []
    for tid, category in TEMPLATES:
        typ = CATEGORY[category]
        max_floors, height, _, _ = TYPOLOGY[typ]
        out.append(
            {
                "id": tid,
                "typology": typ,
                "max_floors": max_floors,
                "values": [
                    {"pointer": "/use/category", "value": category, "doubtful": False},
                    {"pointer": "/generator/template", "value": typ, "doubtful": False},
                    {"pointer": "/massing/floor_height_m", "value": height, "doubtful": True},
                ],
                "source": GENERATOR_REF,
            }
        )
    return out


class QuickBrief(BaseModel):
    """A short brief: what an estimator knows in the first minute."""

    building_type: str = Field(max_length=40)
    gfa_m2: float = Field(gt=0, le=10_000_000)
    storeys: int = Field(ge=1, le=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    quality: Literal["economy", "standard", "high"] = "standard"
    floor_height_m: float | None = Field(default=None, gt=0, le=20)
    depth_m: float | None = Field(default=None, gt=0, le=500)
    grid_m: float | None = Field(default=None, gt=0, le=50)
    wwr: float | None = Field(default=None, ge=0, le=1)
    slab_zone_m: float | None = Field(default=None, ge=0, lt=3)
    plot_area_m2: float | None = Field(default=None, gt=0, le=100_000_000)
    max_height_m: float | None = Field(default=None, gt=0, le=1000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=10)


def _brief(body: QuickBrief) -> dict[str, Any]:
    out = body.model_dump(exclude_none=True)
    if "fx_rate" in out:
        out["fx_rate"] = str(out["fx_rate"])
    return out


def register(router) -> None:
    @router.get("/templates")
    async def list_templates(principal: PrincipalDep) -> dict[str, Any]:
        """Templates for a new project (static: the generator's own typologies)."""
        return {"templates": templates(), "source": GENERATOR_REF}

    @router.get("/quick/types")
    async def quick_types(principal: PrincipalDep) -> dict[str, Any]:
        """Building types the quick massing models, and which of them the generator builds and the band prices."""
        return {"types": quick.types()}

    @router.post("/quick")
    async def quick_build(body: QuickBrief, principal: PrincipalDep) -> dict[str, Any]:
        """Model quantities, elemental cost range and phase programme for a short brief. Nothing is stored."""
        return quick.build(_brief(body))

    @router.post("/projects/{project_id}/quick")
    async def quick_for_project(
        project_id: uuid.UUID, body: QuickBrief, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        """The same in the project's currency and country; the exchange rate comes from the project's own fx_rates
        when it lists the band currency, else from the body (a rate the person confirmed)."""
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one()
        brief = _brief(body)
        if project.currency:
            brief["currency"] = project.currency
        if project.country_code and "country" not in brief:
            brief["country"] = project.country_code
        rate, src = quick.project_fx(brief.get("currency") or "", project.fx_rates)
        if rate:
            brief["fx_rate"], brief["fx_source"] = rate, src
        return quick.build(brief)
