"""Takeoff Pydantic schemas (request/response)."""

from datetime import datetime

from pydantic import BaseModel, Field


class TakeoffDocumentResponse(BaseModel):
    """Response after uploading a PDF document."""

    id: str
    filename: str
    pages: int
    size_bytes: int
    status: str
    content_type: str
    uploaded_at: datetime | None = Field(None, alias="created_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class ExtractedElement(BaseModel):
    """A single element extracted from AI analysis."""

    id: str
    category: str
    description: str
    quantity: float
    unit: str
    confidence: float


class AnalysisResultResponse(BaseModel):
    """AI analysis result for a document."""

    elements: list[ExtractedElement]
    summary: dict


class ExtractTablesResponse(BaseModel):
    """Table extraction result for a document."""

    elements: list[ExtractedElement]
    summary: dict


# ── CAD quantity extraction schemas ──────────────────────────────────────


class CadQuantityItem(BaseModel):
    """Single type-level row in a quantity group."""

    type: str
    material: str = ""
    count: float = 0
    volume_m3: float = 0
    area_m2: float = 0
    length_m: float = 0


class QuantityTotals(BaseModel):
    """Summed quantities for a group or the whole file."""

    count: float = 0
    volume_m3: float = 0
    area_m2: float = 0
    length_m: float = 0


class CadQuantityGroup(BaseModel):
    """A category-level group of quantity items."""

    category: str
    items: list[CadQuantityItem]
    totals: QuantityTotals


class CadExtractResponse(BaseModel):
    """Response from the deterministic CAD quantity extraction endpoint."""

    filename: str
    format: str
    total_elements: int
    duration_ms: int
    groups: list[CadQuantityGroup]
    grand_totals: QuantityTotals
