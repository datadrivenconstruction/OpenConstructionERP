"""/api/v1/design project start: the templates a new project can begin from.

A template is a generator typology (editor spec.rs/limits.rs, see ``model_params``). Picking one proposes the
values below; nothing is written here. The person sees them on the one summary screen with the other proposals,
corrects what is needed and confirms them all; only then do they become brief values.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from . import quick
from .auth import PrincipalDep
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
    gfa_m2: float
    storeys: int
    country: str | None = Field(default=None, max_length=2)
    quality: Literal["economy", "standard", "high"] = "standard"
    floor_height_m: float | None = None
    depth_m: float | None = None
    grid_m: float | None = None
    wwr: float | None = None
    slab_zone_m: float | None = None
    plot_area_m2: float | None = None
    max_height_m: float | None = None
    currency: str | None = Field(default=None, max_length=3)
    fx_rate: str | None = Field(default=None, max_length=20)


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
        return quick.build(body.model_dump(exclude_none=True))
