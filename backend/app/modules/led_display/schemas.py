"""LED Display Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── LED Project schemas ────────────────────────────────────────────────────


class LEDProjectCreate(BaseModel):
    """Create a new LED display project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    display_type: str = Field(
        default="indoor",
        pattern=r"^(indoor|outdoor|semi_outdoor|transparent|curtain|rental)$",
    )
    screen_width_mm: int | None = Field(default=None, ge=0)
    screen_height_mm: int | None = Field(default=None, ge=0)
    pixel_pitch_mm: str | None = Field(default=None, max_length=10)
    resolution_width: int | None = Field(default=None, ge=0)
    resolution_height: int | None = Field(default=None, ge=0)
    brightness_nits: int | None = Field(default=None, ge=0)
    refresh_rate_hz: int | None = Field(default=None, ge=0)
    installation_location: str | None = Field(default=None, max_length=500)
    installation_address: str | None = Field(default=None, max_length=500)
    planned_start_date: str | None = Field(default=None, max_length=20)
    planned_end_date: str | None = Field(default=None, max_length=20)
    vendor_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDProjectUpdate(BaseModel):
    """Partial update for an LED project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    display_type: str | None = Field(
        default=None,
        pattern=r"^(indoor|outdoor|semi_outdoor|transparent|curtain|rental)$",
    )
    screen_width_mm: int | None = Field(default=None, ge=0)
    screen_height_mm: int | None = Field(default=None, ge=0)
    pixel_pitch_mm: str | None = Field(default=None, max_length=10)
    resolution_width: int | None = Field(default=None, ge=0)
    resolution_height: int | None = Field(default=None, ge=0)
    brightness_nits: int | None = Field(default=None, ge=0)
    refresh_rate_hz: int | None = Field(default=None, ge=0)
    installation_location: str | None = Field(default=None, max_length=500)
    installation_address: str | None = Field(default=None, max_length=500)
    status: str | None = Field(
        default=None,
        pattern=r"^(planning|procurement|installation|testing|completed|operational|maintenance)$",
    )
    planned_start_date: str | None = Field(default=None, max_length=20)
    planned_end_date: str | None = Field(default=None, max_length=20)
    actual_start_date: str | None = Field(default=None, max_length=20)
    actual_end_date: str | None = Field(default=None, max_length=20)
    vendor_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class LEDProjectResponse(BaseModel):
    """LED project returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str = ""
    display_type: str = "indoor"
    screen_width_mm: int | None = None
    screen_height_mm: int | None = None
    pixel_pitch_mm: str | None = None
    resolution_width: int | None = None
    resolution_height: int | None = None
    brightness_nits: int | None = None
    refresh_rate_hz: int | None = None
    installation_location: str | None = None
    installation_address: str | None = None
    status: str = "planning"
    planned_start_date: str | None = None
    planned_end_date: str | None = None
    actual_start_date: str | None = None
    actual_end_date: str | None = None
    owner_id: UUID | None = None
    vendor_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Panel schemas ──────────────────────────────────────────────────────


class LEDPanelCreate(BaseModel):
    """Create a new LED panel."""

    model_config = ConfigDict(str_strip_whitespace=True)

    led_project_id: UUID
    panel_id: str = Field(..., min_length=1, max_length=50)
    serial_number: str | None = Field(default=None, max_length=100)
    manufacturer: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    width_mm: int | None = Field(default=None, ge=0)
    height_mm: int | None = Field(default=None, ge=0)
    depth_mm: int | None = Field(default=None, ge=0)
    weight_kg: str | None = Field(default=None, max_length=10)
    pixel_pitch_mm: str | None = Field(default=None, max_length=10)
    resolution_width: int | None = Field(default=None, ge=0)
    resolution_height: int | None = Field(default=None, ge=0)
    brightness_nits: int | None = Field(default=None, ge=0)
    position_row: int | None = Field(default=None, ge=0)
    position_col: int | None = Field(default=None, ge=0)
    status: str = Field(
        default="pending",
        pattern=r"^(pending|installed|tested|operational|damaged|replaced)$",
    )
    unit_cost: str | None = Field(default=None, max_length=20)
    currency: str = Field(default="EUR", max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDPanelUpdate(BaseModel):
    """Partial update for an LED panel."""

    model_config = ConfigDict(str_strip_whitespace=True)

    panel_id: str | None = Field(default=None, max_length=50)
    serial_number: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    width_mm: int | None = Field(default=None, ge=0)
    height_mm: int | None = Field(default=None, ge=0)
    depth_mm: int | None = Field(default=None, ge=0)
    weight_kg: str | None = Field(default=None, max_length=10)
    pixel_pitch_mm: str | None = Field(default=None, max_length=10)
    resolution_width: int | None = Field(default=None, ge=0)
    resolution_height: int | None = Field(default=None, ge=0)
    brightness_nits: int | None = Field(default=None, ge=0)
    position_row: int | None = Field(default=None, ge=0)
    position_col: int | None = Field(default=None, ge=0)
    status: str | None = Field(
        default=None,
        pattern=r"^(pending|installed|tested|operational|damaged|replaced)$",
    )
    unit_cost: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None


class LEDPanelResponse(BaseModel):
    """LED panel returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    led_project_id: UUID
    panel_id: str
    serial_number: str | None = None
    manufacturer: str
    model: str
    width_mm: int | None = None
    height_mm: int | None = None
    depth_mm: int | None = None
    weight_kg: str | None = None
    pixel_pitch_mm: str | None = None
    resolution_width: int | None = None
    resolution_height: int | None = None
    brightness_nits: int | None = None
    position_row: int | None = None
    position_col: int | None = None
    status: str = "pending"
    unit_cost: str | None = None
    currency: str = "EUR"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Controller schemas ─────────────────────────────────────────────────


class LEDControllerCreate(BaseModel):
    """Create a new LED controller."""

    model_config = ConfigDict(str_strip_whitespace=True)

    led_project_id: UUID
    controller_id: str = Field(..., min_length=1, max_length=50)
    serial_number: str | None = Field(default=None, max_length=100)
    manufacturer: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    controller_type: str = Field(
        default="sending",
        pattern=r"^(sending|receiving|hub|video_processor|calibration)$",
    )
    input_connections: int | None = Field(default=None, ge=0)
    output_connections: int | None = Field(default=None, ge=0)
    max_loaded_panels: int | None = Field(default=None, ge=0)
    ip_address: str | None = Field(default=None, max_length=50)
    mac_address: str | None = Field(default=None, max_length=50)
    status: str = Field(
        default="pending",
        pattern=r"^(pending|installed|operational|fault)$",
    )
    unit_cost: str | None = Field(default=None, max_length=20)
    currency: str = Field(default="EUR", max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDControllerUpdate(BaseModel):
    """Partial update for an LED controller."""

    model_config = ConfigDict(str_strip_whitespace=True)

    controller_id: str | None = Field(default=None, max_length=50)
    serial_number: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    controller_type: str | None = Field(
        default=None,
        pattern=r"^(sending|receiving|hub|video_processor|calibration)$",
    )
    input_connections: int | None = Field(default=None, ge=0)
    output_connections: int | None = Field(default=None, ge=0)
    max_loaded_panels: int | None = Field(default=None, ge=0)
    ip_address: str | None = Field(default=None, max_length=50)
    mac_address: str | None = Field(default=None, max_length=50)
    status: str | None = Field(
        default=None,
        pattern=r"^(pending|installed|operational|fault)$",
    )
    unit_cost: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None


class LEDControllerResponse(BaseModel):
    """LED controller returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    led_project_id: UUID
    controller_id: str
    serial_number: str | None = None
    manufacturer: str
    model: str
    controller_type: str = "sending"
    input_connections: int | None = None
    output_connections: int | None = None
    max_loaded_panels: int | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    status: str = "pending"
    unit_cost: str | None = None
    currency: str = "EUR"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Inventory schemas ──────────────────────────────────────────────────


class LEDInventoryCreate(BaseModel):
    """Create a new LED inventory item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    led_project_id: UUID | None = None
    item_name: str = Field(..., min_length=1, max_length=200)
    item_type: str = Field(
        ...,
        pattern=r"^(panel|controller|power_supply|cable|mounting_kit|accessory)$",
    )
    manufacturer: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    sku: str | None = Field(default=None, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)
    quantity_ordered: int = Field(default=0, ge=0)
    quantity_received: int = Field(default=0, ge=0)
    quantity_used: int = Field(default=0, ge=0)
    quantity_in_stock: int = Field(default=0, ge=0)
    warehouse_location: str | None = Field(default=None, max_length=200)
    unit_cost: str | None = Field(default=None, max_length=20)
    total_cost: str | None = Field(default=None, max_length=20)
    currency: str = Field(default="EUR", max_length=10)
    status: str = Field(
        default="ordered",
        pattern=r"^(ordered|partial|received|allocated|used|returned)$",
    )
    supplier_id: UUID | None = None
    order_date: str | None = Field(default=None, max_length=20)
    expected_delivery: str | None = Field(default=None, max_length=20)
    received_date: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDInventoryUpdate(BaseModel):
    """Partial update for an LED inventory item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    item_name: str | None = Field(default=None, max_length=200)
    item_type: str | None = Field(
        default=None,
        pattern=r"^(panel|controller|power_supply|cable|mounting_kit|accessory)$",
    )
    manufacturer: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    sku: str | None = Field(default=None, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)
    quantity_ordered: int | None = Field(default=None, ge=0)
    quantity_received: int | None = Field(default=None, ge=0)
    quantity_used: int | None = Field(default=None, ge=0)
    quantity_in_stock: int | None = Field(default=None, ge=0)
    warehouse_location: str | None = Field(default=None, max_length=200)
    unit_cost: str | None = Field(default=None, max_length=20)
    total_cost: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, max_length=10)
    status: str | None = Field(
        default=None,
        pattern=r"^(ordered|partial|received|allocated|used|returned)$",
    )
    supplier_id: UUID | None = None
    order_date: str | None = Field(default=None, max_length=20)
    expected_delivery: str | None = Field(default=None, max_length=20)
    received_date: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] | None = None


class LEDInventoryResponse(BaseModel):
    """LED inventory item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    led_project_id: UUID | None = None
    item_name: str
    item_type: str
    manufacturer: str | None = None
    model: str | None = None
    sku: str | None = None
    serial_number: str | None = None
    quantity_ordered: int = 0
    quantity_received: int = 0
    quantity_used: int = 0
    quantity_in_stock: int = 0
    warehouse_location: str | None = None
    unit_cost: str | None = None
    total_cost: str | None = None
    currency: str = "EUR"
    status: str = "ordered"
    supplier_id: UUID | None = None
    order_date: str | None = None
    expected_delivery: str | None = None
    received_date: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Installation schemas ───────────────────────────────────────────────


class LEDInstallationCreate(BaseModel):
    """Create a new LED installation record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    led_project_id: UUID
    installation_type: str = Field(
        ...,
        pattern=r"^(structural|electrical|panel_mounting|controller_config|testing|commissioning)$",
    )
    description: str = Field(default="", max_length=5000)
    progress_pct: int = Field(default=0, ge=0, le=100)
    status: str = Field(
        default="pending",
        pattern=r"^(pending|in_progress|completed|verified|issues)$",
    )
    scheduled_date: str | None = Field(default=None, max_length=20)
    started_date: str | None = Field(default=None, max_length=20)
    completed_date: str | None = Field(default=None, max_length=20)
    assigned_team: str | None = Field(default=None, max_length=200)
    lead_technician_id: UUID | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDInstallationUpdate(BaseModel):
    """Partial update for an LED installation record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    installation_type: str | None = Field(
        default=None,
        pattern=r"^(structural|electrical|panel_mounting|controller_config|testing|commissioning)$",
    )
    description: str | None = Field(default=None, max_length=5000)
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    status: str | None = Field(
        default=None,
        pattern=r"^(pending|in_progress|completed|verified|issues)$",
    )
    scheduled_date: str | None = Field(default=None, max_length=20)
    started_date: str | None = Field(default=None, max_length=20)
    completed_date: str | None = Field(default=None, max_length=20)
    assigned_team: str | None = Field(default=None, max_length=200)
    lead_technician_id: UUID | None = None
    issues: list[dict[str, Any]] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None


class LEDInstallationResponse(BaseModel):
    """LED installation record returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    led_project_id: UUID
    installation_type: str
    description: str = ""
    progress_pct: int = 0
    status: str = "pending"
    scheduled_date: str | None = None
    started_date: str | None = None
    completed_date: str | None = None
    assigned_team: str | None = None
    lead_technician_id: UUID | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Milestone schemas ──────────────────────────────────────────────────


class LEDMilestoneCreate(BaseModel):
    """Create a new LED milestone."""

    model_config = ConfigDict(str_strip_whitespace=True)

    led_project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    milestone_type: str = Field(
        default="general",
        pattern=r"^(general|procurement|structural|electrical|installation|testing|commissioning|handover)$",
    )
    description: str | None = Field(default=None, max_length=2000)
    planned_date: str | None = Field(default=None, max_length=20)
    actual_date: str | None = Field(default=None, max_length=20)
    status: str = Field(
        default="pending",
        pattern=r"^(pending|in_progress|completed|delayed|cancelled)$",
    )
    linked_payment_pct: str | None = Field(default=None, max_length=10)
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDMilestoneUpdate(BaseModel):
    """Partial update for an LED milestone."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    milestone_type: str | None = Field(
        default=None,
        pattern=r"^(general|procurement|structural|electrical|installation|testing|commissioning|handover)$",
    )
    description: str | None = Field(default=None, max_length=2000)
    planned_date: str | None = Field(default=None, max_length=20)
    actual_date: str | None = Field(default=None, max_length=20)
    status: str | None = Field(
        default=None,
        pattern=r"^(pending|in_progress|completed|delayed|cancelled)$",
    )
    linked_payment_pct: str | None = Field(default=None, max_length=10)
    criteria: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class LEDMilestoneResponse(BaseModel):
    """LED milestone returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    led_project_id: UUID
    name: str
    milestone_type: str = "general"
    description: str | None = None
    planned_date: str | None = None
    actual_date: str | None = None
    status: str = "pending"
    linked_payment_pct: str | None = None
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Maintenance Log schemas ─────────────────────────────────────────────


class LEDMaintenanceLogCreate(BaseModel):
    """Create a new LED maintenance log."""

    model_config = ConfigDict(str_strip_whitespace=True)

    led_project_id: UUID
    maintenance_type: str = Field(
        ...,
        pattern=r"^(preventive|corrective|emergency|inspection|calibration|cleaning)$",
    )
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=10000)
    status: str = Field(
        default="scheduled",
        pattern=r"^(scheduled|in_progress|completed|cancelled)$",
    )
    scheduled_date: str | None = Field(default=None, max_length=20)
    started_date: str | None = Field(default=None, max_length=20)
    completed_date: str | None = Field(default=None, max_length=20)
    performed_by: str | None = Field(default=None, max_length=200)
    technician_id: UUID | None = None
    work_performed: str | None = Field(default=None, max_length=5000)
    parts_replaced: list[dict[str, Any]] = Field(default_factory=list)
    labor_cost: str | None = Field(default=None, max_length=20)
    parts_cost: str | None = Field(default=None, max_length=20)
    total_cost: str | None = Field(default=None, max_length=20)
    currency: str = Field(default="EUR", max_length=10)
    next_maintenance_date: str | None = Field(default=None, max_length=20)
    next_maintenance_type: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDMaintenanceLogUpdate(BaseModel):
    """Partial update for an LED maintenance log."""

    model_config = ConfigDict(str_strip_whitespace=True)

    maintenance_type: str | None = Field(
        default=None,
        pattern=r"^(preventive|corrective|emergency|inspection|calibration|cleaning)$",
    )
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    status: str | None = Field(
        default=None,
        pattern=r"^(scheduled|in_progress|completed|cancelled)$",
    )
    scheduled_date: str | None = Field(default=None, max_length=20)
    started_date: str | None = Field(default=None, max_length=20)
    completed_date: str | None = Field(default=None, max_length=20)
    performed_by: str | None = Field(default=None, max_length=200)
    technician_id: UUID | None = None
    work_performed: str | None = Field(default=None, max_length=5000)
    parts_replaced: list[dict[str, Any]] | None = None
    labor_cost: str | None = Field(default=None, max_length=20)
    parts_cost: str | None = Field(default=None, max_length=20)
    total_cost: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, max_length=10)
    next_maintenance_date: str | None = Field(default=None, max_length=20)
    next_maintenance_type: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None


class LEDMaintenanceLogResponse(BaseModel):
    """LED maintenance log returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    led_project_id: UUID
    maintenance_type: str
    title: str
    description: str
    status: str = "scheduled"
    scheduled_date: str | None = None
    started_date: str | None = None
    completed_date: str | None = None
    performed_by: str | None = None
    technician_id: UUID | None = None
    work_performed: str | None = None
    parts_replaced: list[dict[str, Any]] = Field(default_factory=list)
    labor_cost: str | None = None
    parts_cost: str | None = None
    total_cost: str | None = None
    currency: str = "EUR"
    next_maintenance_date: str | None = None
    next_maintenance_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Document schemas ───────────────────────────────────────────────────


class LEDDocumentCreate(BaseModel):
    """Create a new LED document."""

    model_config = ConfigDict(str_strip_whitespace=True)

    led_project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    document_type: str = Field(
        ...,
        pattern=r"^(wiring_diagram|schematic|specification|manual|certificate|inspection_report|warranty|contract|photo|other)$",
    )
    description: str | None = Field(default=None, max_length=2000)
    file_path: str | None = Field(default=None, max_length=500)
    file_name: str | None = Field(default=None, max_length=255)
    file_size: int | None = Field(default=None, ge=0)
    mime_type: str | None = Field(default=None, max_length=100)
    version: str = Field(default="1.0", max_length=20)
    status: str = Field(
        default="active",
        pattern=r"^(active|archived|superseded)$",
    )
    document_date: str | None = Field(default=None, max_length=20)
    external_url: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDDocumentUpdate(BaseModel):
    """Partial update for an LED document."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    document_type: str | None = Field(
        default=None,
        pattern=r"^(wiring_diagram|schematic|specification|manual|certificate|inspection_report|warranty|contract|photo|other)$",
    )
    description: str | None = Field(default=None, max_length=2000)
    file_path: str | None = Field(default=None, max_length=500)
    file_name: str | None = Field(default=None, max_length=255)
    file_size: int | None = Field(default=None, ge=0)
    mime_type: str | None = Field(default=None, max_length=100)
    version: str | None = Field(default=None, max_length=20)
    status: str | None = Field(
        default=None,
        pattern=r"^(active|archived|superseded)$",
    )
    document_date: str | None = Field(default=None, max_length=20)
    external_url: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] | None = None


class LEDDocumentResponse(BaseModel):
    """LED document returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    led_project_id: UUID
    name: str
    document_type: str
    description: str | None = None
    file_path: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    version: str = "1.0"
    status: str = "active"
    document_date: str | None = None
    uploaded_date: str | None = None
    uploaded_by: UUID | None = None
    external_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Budget schemas ─────────────────────────────────────────────────────


class LEDBudgetCreate(BaseModel):
    """Create a new LED budget entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    led_project_id: UUID
    category: str = Field(
        ...,
        pattern=r"^(hardware|labor|materials|transportation|installation|testing|commissioning|maintenance|contingency|other)$",
    )
    description: str | None = Field(default=None, max_length=2000)
    planned_amount: str = Field(default="0", max_length=20)
    actual_amount: str = Field(default="0", max_length=20)
    committed_amount: str = Field(default="0", max_length=20)
    currency: str = Field(default="EUR", max_length=10)
    status: str = Field(
        default="planned",
        pattern=r"^(planned|approved|in_progress|completed|over_budget)$",
    )
    breakdown: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LEDBudgetUpdate(BaseModel):
    """Partial update for an LED budget entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(
        default=None,
        pattern=r"^(hardware|labor|materials|transportation|installation|testing|commissioning|maintenance|contingency|other)$",
    )
    description: str | None = Field(default=None, max_length=2000)
    planned_amount: str | None = Field(default=None, max_length=20)
    actual_amount: str | None = Field(default=None, max_length=20)
    committed_amount: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, max_length=10)
    status: str | None = Field(
        default=None,
        pattern=r"^(planned|approved|in_progress|completed|over_budget)$",
    )
    breakdown: list[dict[str, Any]] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class LEDBudgetResponse(BaseModel):
    """LED budget entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    led_project_id: UUID
    category: str
    description: str | None = None
    planned_amount: str = "0"
    actual_amount: str = "0"
    committed_amount: str = "0"
    currency: str = "EUR"
    status: str = "planned"
    breakdown: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── LED Statistics schemas ─────────────────────────────────────────────────


class LEDProjectStatsResponse(BaseModel):
    """Dashboard KPIs for an LED project."""

    total_panels: int = 0
    installed_panels: int = 0
    operational_panels: int = 0
    damaged_panels: int = 0
    
    total_controllers: int = 0
    operational_controllers: int = 0
    faulty_controllers: int = 0
    
    total_budget: str = "0"
    spent_budget: str = "0"
    remaining_budget: str = "0"
    
    completed_milestones: int = 0
    pending_milestones: int = 0
    
    installation_progress_pct: int = 0
    
    maintenance_logs_count: int = 0
    upcoming_maintenance: int = 0
    
    documents_count: int = 0
    
    inventory_items_count: int = 0
    low_stock_items: int = 0


class LEDProjectSummaryResponse(BaseModel):
    """Summary response for LED projects list."""

    id: UUID
    project_id: UUID
    name: str
    display_type: str
    status: str
    screen_width_mm: int | None = None
    screen_height_mm: int | None = None
    installation_location: str | None = None
    planned_end_date: str | None = None
    panels_count: int = 0
    installation_progress_pct: int = 0
    created_at: datetime