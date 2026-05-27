"""‌⁠‍Carbon & Sustainability Pydantic schemas — request/response models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── EPD Record ────────────────────────────────────────────────────────────


class EPDRecordCreate(BaseModel):
    """‌⁠‍Create an EPD record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    epd_id: str = Field(..., min_length=1, max_length=120)
    source: str = Field(
        default="custom",
        pattern=r"^(oekobaudat|ice|ec3|epd_international|custom)$",
    )
    material_class: str = Field(..., min_length=1, max_length=80)
    product_name: str = Field(..., min_length=1, max_length=500)
    manufacturer: str | None = Field(default=None, max_length=255)
    region: str = Field(default="", max_length=8)
    declared_unit: str = Field(default="kg", max_length=20)
    gwp_a1a3: Decimal = Field(default=Decimal("0"))
    gwp_a4: Decimal | None = None
    gwp_a5: Decimal | None = None
    gwp_b_total: Decimal | None = None
    gwp_c_total: Decimal | None = None
    gwp_d_credits: Decimal | None = None
    validity_until: date | None = None
    document_url: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EPDRecordUpdate(BaseModel):
    """‌⁠‍Partial update of an EPD record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source: str | None = Field(
        default=None,
        pattern=r"^(oekobaudat|ice|ec3|epd_international|custom)$",
    )
    material_class: str | None = Field(default=None, max_length=80)
    product_name: str | None = Field(default=None, max_length=500)
    manufacturer: str | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=8)
    declared_unit: str | None = Field(default=None, max_length=20)
    gwp_a1a3: Decimal | None = None
    gwp_a4: Decimal | None = None
    gwp_a5: Decimal | None = None
    gwp_b_total: Decimal | None = None
    gwp_c_total: Decimal | None = None
    gwp_d_credits: Decimal | None = None
    validity_until: date | None = None
    document_url: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, Any] | None = None


class EPDRecordResponse(BaseModel):
    """EPD record returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    epd_id: str
    source: str
    material_class: str
    product_name: str
    manufacturer: str | None = None
    region: str
    declared_unit: str
    gwp_a1a3: Decimal
    gwp_a4: Decimal | None = None
    gwp_a5: Decimal | None = None
    gwp_b_total: Decimal | None = None
    gwp_c_total: Decimal | None = None
    gwp_d_credits: Decimal | None = None
    validity_until: date | None = None
    document_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Material Carbon Factor ────────────────────────────────────────────────


class MaterialCarbonFactorCreate(BaseModel):
    """Create a material carbon factor."""

    cost_item_id: UUID | None = None
    epd_id: UUID | None = None
    manual_override_factor: Decimal | None = None
    unit_for_factor: str = Field(default="kg", max_length=20)
    region: str = Field(default="", max_length=8)
    last_reviewed_at: date | None = None
    confidence: str = Field(default="medium", pattern=r"^(high|medium|low)$")
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MaterialCarbonFactorUpdate(BaseModel):
    """Partial update of a material carbon factor."""

    cost_item_id: UUID | None = None
    epd_id: UUID | None = None
    manual_override_factor: Decimal | None = None
    unit_for_factor: str | None = Field(default=None, max_length=20)
    region: str | None = Field(default=None, max_length=8)
    last_reviewed_at: date | None = None
    confidence: str | None = Field(default=None, pattern=r"^(high|medium|low)$")
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class MaterialCarbonFactorResponse(BaseModel):
    """Material carbon factor returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    cost_item_id: UUID | None = None
    epd_id: UUID | None = None
    manual_override_factor: Decimal | None = None
    unit_for_factor: str
    region: str
    last_reviewed_at: date | None = None
    confidence: str
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Carbon Inventory ─────────────────────────────────────────────────────


class CarbonInventoryCreate(BaseModel):
    """Create a carbon inventory."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="Baseline inventory", max_length=255)
    scope: str = Field(
        default="cradle_to_gate",
        pattern=r"^(cradle_to_gate|cradle_to_grave|operational)$",
    )
    as_of_date: date | None = None
    status: str = Field(
        default="draft",
        pattern=r"^(draft|baseline|current|archived)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CarbonInventoryUpdate(BaseModel):
    """Partial update of an inventory."""

    name: str | None = Field(default=None, max_length=255)
    scope: str | None = Field(
        default=None,
        pattern=r"^(cradle_to_gate|cradle_to_grave|operational)$",
    )
    as_of_date: date | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|baseline|current|archived)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class CarbonInventoryResponse(BaseModel):
    """Carbon inventory returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    scope: str
    as_of_date: date | None = None
    status: str
    totals: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Embodied Carbon Entry ─────────────────────────────────────────────────


class EmbodiedCarbonEntryCreate(BaseModel):
    """Create an embodied-carbon entry."""

    inventory_id: UUID
    element_ref: str | None = Field(default=None, max_length=255)
    description: str = Field(default="", max_length=10000)
    quantity: Decimal = Field(default=Decimal("0"))
    unit: str = Field(default="kg", max_length=20)
    factor_id: UUID | None = None
    factor_value_used: Decimal = Field(default=Decimal("0"))
    carbon_kg: Decimal = Field(default=Decimal("0"))
    stage: str = Field(default="a1a3", pattern=r"^(a1a3|a4|a5|b|c|d)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbodiedCarbonEntryUpdate(BaseModel):
    """Partial update of an embodied-carbon entry."""

    element_ref: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=20)
    factor_id: UUID | None = None
    factor_value_used: Decimal | None = None
    carbon_kg: Decimal | None = None
    stage: str | None = Field(default=None, pattern=r"^(a1a3|a4|a5|b|c|d)$")
    metadata: dict[str, Any] | None = None


class EmbodiedCarbonEntryResponse(BaseModel):
    """Embodied entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    inventory_id: UUID
    element_ref: str | None = None
    description: str
    quantity: Decimal
    unit: str
    factor_id: UUID | None = None
    factor_value_used: Decimal
    carbon_kg: Decimal
    stage: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EmbodiedBulkCreate(BaseModel):
    """Bulk create payload."""

    entries: list[EmbodiedCarbonEntryCreate] = Field(default_factory=list)


# ── Scope 1 / 2 / 3 ───────────────────────────────────────────────────────


class Scope1EntryCreate(BaseModel):
    """Create a scope-1 (direct) emission entry."""

    inventory_id: UUID
    period_start: date
    period_end: date
    fuel_type: str = Field(
        default="diesel",
        pattern=r"^(diesel|petrol|lpg|natural_gas|other)$",
    )
    litres_or_m3: Decimal = Field(default=Decimal("0"))
    emission_factor_kg_co2e_per_unit: Decimal = Field(default=Decimal("0"))
    total_co2e_kg: Decimal | None = None
    source: str = Field(
        default="manual",
        pattern=r"^(equipment_telematics|fuel_log|manual)$",
    )
    source_ref: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scope1EntryUpdate(BaseModel):
    """Partial update of a scope-1 entry."""

    period_start: date | None = None
    period_end: date | None = None
    fuel_type: str | None = Field(
        default=None,
        pattern=r"^(diesel|petrol|lpg|natural_gas|other)$",
    )
    litres_or_m3: Decimal | None = None
    emission_factor_kg_co2e_per_unit: Decimal | None = None
    total_co2e_kg: Decimal | None = None
    source: str | None = Field(
        default=None,
        pattern=r"^(equipment_telematics|fuel_log|manual)$",
    )
    source_ref: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class Scope1EntryResponse(BaseModel):
    """Scope-1 entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    inventory_id: UUID
    period_start: date
    period_end: date
    fuel_type: str
    litres_or_m3: Decimal
    emission_factor_kg_co2e_per_unit: Decimal
    total_co2e_kg: Decimal
    source: str
    source_ref: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class Scope2EntryCreate(BaseModel):
    """Create a scope-2 (purchased-energy) emission entry."""

    inventory_id: UUID
    period_start: date
    period_end: date
    energy_type: str = Field(
        default="grid_electricity",
        pattern=r"^(grid_electricity|district_heating|cooling)$",
    )
    kwh: Decimal = Field(default=Decimal("0"))
    emission_factor_kg_co2e_per_kwh: Decimal = Field(default=Decimal("0"))
    market_or_location: str = Field(default="location", pattern=r"^(market|location)$")
    total_co2e_kg: Decimal | None = None
    supplier_name: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scope2EntryUpdate(BaseModel):
    """Partial update of a scope-2 entry."""

    period_start: date | None = None
    period_end: date | None = None
    energy_type: str | None = Field(
        default=None,
        pattern=r"^(grid_electricity|district_heating|cooling)$",
    )
    kwh: Decimal | None = None
    emission_factor_kg_co2e_per_kwh: Decimal | None = None
    market_or_location: str | None = Field(default=None, pattern=r"^(market|location)$")
    total_co2e_kg: Decimal | None = None
    supplier_name: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class Scope2EntryResponse(BaseModel):
    """Scope-2 entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    inventory_id: UUID
    period_start: date
    period_end: date
    energy_type: str
    kwh: Decimal
    emission_factor_kg_co2e_per_kwh: Decimal
    market_or_location: str
    total_co2e_kg: Decimal
    supplier_name: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class Scope3EntryCreate(BaseModel):
    """Create a scope-3 (other) emission entry."""

    inventory_id: UUID
    period_start: date
    period_end: date
    category: str = Field(
        default="transport_upstream",
        pattern=r"^(transport_upstream|transport_downstream|waste|business_travel|other)$",
    )
    description: str = Field(default="", max_length=10000)
    activity_data: Decimal = Field(default=Decimal("0"))
    activity_unit: str = Field(default="tkm", max_length=40)
    emission_factor: Decimal = Field(default=Decimal("0"))
    total_co2e_kg: Decimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scope3EntryUpdate(BaseModel):
    """Partial update of a scope-3 entry."""

    period_start: date | None = None
    period_end: date | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(transport_upstream|transport_downstream|waste|business_travel|other)$",
    )
    description: str | None = Field(default=None, max_length=10000)
    activity_data: Decimal | None = None
    activity_unit: str | None = Field(default=None, max_length=40)
    emission_factor: Decimal | None = None
    total_co2e_kg: Decimal | None = None
    metadata: dict[str, Any] | None = None


class Scope3EntryResponse(BaseModel):
    """Scope-3 entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    inventory_id: UUID
    period_start: date
    period_end: date
    category: str
    description: str
    activity_data: Decimal
    activity_unit: str
    emission_factor: Decimal
    total_co2e_kg: Decimal
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Targets ──────────────────────────────────────────────────────────────


class CarbonTargetCreate(BaseModel):
    """Create a carbon-reduction target."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    target_type: str = Field(
        default="absolute",
        pattern=r"^(intensity_per_m2|intensity_per_unit|absolute)$",
    )
    baseline_value: Decimal = Field(default=Decimal("0"))
    target_value: Decimal = Field(default=Decimal("0"))
    baseline_year: int = Field(default=2020, ge=1990, le=2100)
    target_year: int = Field(default=2030, ge=1990, le=2100)
    scope_set: list[str] = Field(default_factory=list)
    status: str = Field(
        default="active",
        pattern=r"^(active|met|missed|abandoned)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CarbonTargetUpdate(BaseModel):
    """Partial update of a target."""

    name: str | None = Field(default=None, max_length=255)
    target_type: str | None = Field(
        default=None,
        pattern=r"^(intensity_per_m2|intensity_per_unit|absolute)$",
    )
    baseline_value: Decimal | None = None
    target_value: Decimal | None = None
    baseline_year: int | None = Field(default=None, ge=1990, le=2100)
    target_year: int | None = Field(default=None, ge=1990, le=2100)
    scope_set: list[str] | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(active|met|missed|abandoned)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class CarbonTargetResponse(BaseModel):
    """Target returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    target_type: str
    baseline_value: Decimal
    target_value: Decimal
    baseline_year: int
    target_year: int
    scope_set: list[str] = Field(default_factory=list)
    status: str
    notes: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class TargetProgressResponse(BaseModel):
    """Progress snapshot for a target."""

    target_id: UUID
    current_value: Decimal
    baseline_value: Decimal
    target_value: Decimal
    progress_pct: float
    met: bool
    as_of_date: date | None = None


# ── Sustainability Report ────────────────────────────────────────────────


class SustainabilityReportCreate(BaseModel):
    """Create a sustainability report record (manual)."""

    project_id: UUID
    inventory_id: UUID | None = None
    period_start: date
    period_end: date
    framework: str = Field(
        default="ghg_protocol",
        pattern=r"^(ghg_protocol|gri|issb|custom)$",
    )
    totals: dict[str, Any] = Field(default_factory=dict)
    narrative: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SustainabilityReportUpdate(BaseModel):
    """Partial update of a sustainability report."""

    inventory_id: UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    framework: str | None = Field(
        default=None,
        pattern=r"^(ghg_protocol|gri|issb|custom)$",
    )
    totals: dict[str, Any] | None = None
    narrative: str | None = None
    metadata: dict[str, Any] | None = None


class SustainabilityReportResponse(BaseModel):
    """Sustainability report returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    inventory_id: UUID | None = None
    period_start: date
    period_end: date
    framework: str
    totals: dict[str, Any] = Field(default_factory=dict)
    narrative: str | None = None
    generated_at: date | None = None
    generated_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class SustainabilityReportPayload(BaseModel):
    """Request to generate a sustainability report."""

    project_id: UUID
    inventory_id: UUID | None = None
    period_start: date
    period_end: date
    framework: str = Field(
        default="ghg_protocol",
        pattern=r"^(ghg_protocol|gri|issb|custom)$",
    )
    project_area_m2: Decimal | None = None
    narrative: str | None = None


# ── Computed views ───────────────────────────────────────────────────────


class InventoryTotalsResponse(BaseModel):
    """Fresh totals for an inventory."""

    inventory_id: UUID
    embodied_a1a3: Decimal = Field(default=Decimal("0"))
    embodied_a4: Decimal = Field(default=Decimal("0"))
    embodied_a5: Decimal = Field(default=Decimal("0"))
    embodied_a1a5: Decimal = Field(default=Decimal("0"))
    embodied_b: Decimal = Field(default=Decimal("0"))
    embodied_c: Decimal = Field(default=Decimal("0"))
    embodied_d: Decimal = Field(default=Decimal("0"))
    scope1: Decimal = Field(default=Decimal("0"))
    scope2: Decimal = Field(default=Decimal("0"))
    scope3: Decimal = Field(default=Decimal("0"))
    operational: Decimal = Field(default=Decimal("0"))
    end_of_life: Decimal = Field(default=Decimal("0"))
    total: Decimal = Field(default=Decimal("0"))


class AlternativeMaterialOption(BaseModel):
    """A single alternative-material option."""

    factor_id: UUID
    factor_value: Decimal
    carbon_kg: Decimal
    savings_kg: Decimal
    savings_pct: float
    confidence: str


class AlternativeComparisonResponse(BaseModel):
    """Alternative-materials comparison for one embodied entry."""

    entry_id: UUID
    current_factor_value: Decimal
    current_carbon_kg: Decimal
    options: list[AlternativeMaterialOption] = Field(default_factory=list)


class CarbonDashboardResponse(BaseModel):
    """Project carbon dashboard payload."""

    project_id: UUID
    total_embodied_kg: Decimal = Field(default=Decimal("0"))
    total_operational_kg: Decimal = Field(default=Decimal("0"))
    total_kg: Decimal = Field(default=Decimal("0"))
    inventory_count: int = 0
    target_count: int = 0
    targets_met: int = 0
    targets_missed: int = 0
    intensity_per_m2: Decimal | None = None
    latest_report_id: UUID | None = None
