# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response bodies of the plan editor routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EditOpKind = Literal["create", "update", "delete", "revert"]


class ViewTransformOut(BaseModel):
    kind: Literal["polynomial", "local"]
    epsg: int | None = None
    crs_name: str = ""
    e0: float
    n0: float
    s: float
    lon: list[float]
    lat: list[float]
    lon0: float
    lat0: float
    q: float
    e: list[float]
    n: list[float]
    residual_mm: float
    grid_north_bearing: float
    extent: list[float] | None = None


class CodeEntryIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    label: str = Field(default="", max_length=120)
    symbol: str = Field(default="spot", max_length=32)
    line: Literal["none", "open", "closed"] = "none"
    smooth: bool = False
    layer: str = Field(default="points", max_length=32)
    colour: str = Field(default="topo", max_length=32, pattern=r"^[a-z0-9-]+$")

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class CodeLibraryIn(BaseModel):
    """``items=None`` drops the project's own library and returns to the default."""

    items: list[CodeEntryIn] | None = Field(default=None, max_length=500)


class CodeLibraryOut(BaseModel):
    items: list[dict[str, Any]]
    source: Literal["project", "pack", "neutral"]
    countries: list[str] = Field(default_factory=list)


class PlanSettingsIn(BaseModel):
    """``conventions=None`` drops the project's own settings."""

    conventions: dict[str, Any] | None = None


class PlanSettingsOut(BaseModel):
    conventions: dict[str, Any]
    defaults: dict[str, Any]
    source: Literal["project", "country", "neutral"]
    country: str | None = None
    csf: float | None = None


class PlanPointOut(BaseModel):
    id: str
    point_id: str
    e: float
    n: float
    z: float | None = None
    code: str = ""
    kind: str = "topo"
    source_line: int | None = None
    rev: int = 0


class PlanPointsOut(BaseModel):
    items: list[PlanPointOut]


class SketchOut(BaseModel):
    features: list[dict[str, Any]]


class EditOpIn(BaseModel):
    entity_type: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    entity_id: str | None = Field(default=None, max_length=64)
    op: EditOpKind
    base_rev: int | None = Field(default=None, ge=0)
    after: dict[str, Any] | None = None
    note: str = Field(default="", max_length=2000)
    client_id: str = Field(default="", max_length=80)


class EditBatchIn(BaseModel):
    ops: list[EditOpIn] = Field(min_length=1, max_length=2000)


class SaveResultOut(BaseModel):
    client_id: str
    entity_type: str
    entity_id: str
    rev: int
    edit_id: str


class SaveBatchOut(BaseModel):
    items: list[SaveResultOut]


class EditRowOut(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    rev: int
    op: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    author: str | None = None
    author_name: str = ""
    created_at: datetime
    note: str = ""
    summary: str = ""


class EditListOut(BaseModel):
    items: list[EditRowOut]


class RestoreIn(BaseModel):
    note: str = Field(default="", max_length=2000)
