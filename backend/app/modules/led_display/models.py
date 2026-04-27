# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""LED Display ORM models.

Tables:
    oe_led_project               — LED display project tracking
    oe_led_panel                 — LED panel inventory and specifications
    oe_led_controller            — LED controller hardware
    oe_led_inventory             — Inventory tracking for LED hardware
    oe_led_installation          — Installation records and progress
    oe_led_milestone             — Project milestones for LED work
    oe_led_maintenance_log       — Maintenance history and logs
    oe_led_document              — Digital documentation repository
    oe_led_budget                — Budget tracking for LED projects
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class LEDProject(Base):
    """LED Display project for construction and infrastructure initiatives."""

    __tablename__ = "oe_led_project"

    # Project linkage
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # LED specifications
    display_type: Mapped[str] = mapped_column(String(50), nullable=False, default="indoor")
    # indoor, outdoor, semi-outdoor, transparent, curtain, rental
    
    screen_width_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_height_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pixel_pitch_mm: Mapped[float | None] = mapped_column(String(10), nullable=True)
    resolution_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    brightness_nits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refresh_rate_hz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Location details
    installation_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    installation_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planning", index=True)
    # planning, procurement, installation, testing, completed, operational, maintenance
    
    # Dates
    planned_start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    planned_end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # Owner
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    # Vendor info
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_contacts_contact.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Additional data
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    panels: Mapped[list["LEDPanel"]] = relationship(
        back_populates="led_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    controllers: Mapped[list["LEDController"]] = relationship(
        back_populates="led_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    inventory_items: Mapped[list["LEDInventory"]] = relationship(
        back_populates="led_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    installations: Mapped[list["LEDInstallation"]] = relationship(
        back_populates="led_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    milestones: Mapped[list["LEDMilestone"]] = relationship(
        back_populates="led_project",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="LEDMilestone.planned_date",
    )
    maintenance_logs: Mapped[list["LEDMaintenanceLog"]] = relationship(
        back_populates="led_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    documents: Mapped[list["LEDDocument"]] = relationship(
        back_populates="led_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    budgets: Mapped[list["LEDBudget"]] = relationship(
        back_populates="led_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<LEDProject {self.name} ({self.status})>"


class LEDPanel(Base):
    """LED panel specifications and inventory."""

    __tablename__ = "oe_led_panel"

    led_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_led_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Panel identification
    panel_id: Mapped[str] = mapped_column(String(50), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manufacturer: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Physical specs
    width_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depth_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(String(10), nullable=True)
    
    # Display specs
    pixel_pitch_mm: Mapped[float | None] = mapped_column(String(10), nullable=True)
    resolution_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brightness_nits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Panel position in display
    position_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_col: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    # pending, installed, tested, operational, damaged, replaced
    
    # Cost
    unit_cost: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    led_project: Mapped[LEDProject] = relationship(back_populates="panels")

    def __repr__(self) -> str:
        return f"<LEDPanel {self.panel_id} ({self.manufacturer} {self.model})>"


class LEDController(Base):
    """LED controller hardware for display management."""

    __tablename__ = "oe_led_controller"

    led_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_led_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Controller identification
    controller_id: Mapped[str] = mapped_column(String(50), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manufacturer: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Technical specs
    controller_type: Mapped[str] = mapped_column(String(50), nullable=False, default="sending")
    # sending, receiving, hub, video processor, calibration
    
    input_connections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_connections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_loaded_panels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Network
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mac_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    # pending, installed, operational, fault
    
    # Cost
    unit_cost: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    led_project: Mapped[LEDProject] = relationship(back_populates="controllers")

    def __repr__(self) -> str:
        return f"<LEDController {self.controller_id} ({self.manufacturer} {self.model})>"


class LEDInventory(Base):
    """Inventory tracking for LED hardware materials."""

    __tablename__ = "oe_led_inventory"

    led_project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_led_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Item identification
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # panel, controller, power_supply, cable, mounting_kit, accessory
    
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    # Quantities
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_in_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Location
    warehouse_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    
    # Cost
    unit_cost: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_cost: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    
    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ordered")
    # ordered, partial, received, allocated, used, returned
    
    # Supplier
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_contacts_contact.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Dates
    order_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expected_delivery: Mapped[str | None] = mapped_column(String(20), nullable=True)
    received_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    led_project: Mapped[LEDProject | None] = relationship(back_populates="inventory_items")

    def __repr__(self) -> str:
        return f"<LEDInventory {self.item_name} ({self.item_type})>"


class LEDInstallation(Base):
    """Installation records and progress tracking."""

    __tablename__ = "oe_led_installation"

    led_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_led_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Installation details
    installation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # structural, electrical, panel_mounting, controller_config, testing, commissioning
    
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    
    # Progress
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    # pending, in_progress, completed, verified, issues
    
    # Schedule
    scheduled_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    completed_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # Team
    assigned_team: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lead_technician_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Issues
    issues: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # [{issue_description, severity, resolved, resolution_date}]
    
    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    led_project: Mapped[LEDProject] = relationship(back_populates="installations")

    def __repr__(self) -> str:
        return f"<LEDInstallation {self.installation_type} ({self.progress_pct}%)>"


class LEDMilestone(Base):
    """Project milestones for LED display work."""

    __tablename__ = "oe_led_milestone"

    led_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_led_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    milestone_type: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    # procurement, structural, electrical, installation, testing, commissioning, handover
    
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    planned_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    # pending, in_progress, completed, delayed, cancelled
    
    # Payment related
    linked_payment_pct: Mapped[str | None] = mapped_column(String(10), nullable=True)
    
    # Completion criteria
    criteria: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # [{criterion, completed, completed_date}]
    
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    led_project: Mapped[LEDProject] = relationship(back_populates="milestones")

    def __repr__(self) -> str:
        return f"<LEDMilestone {self.name} ({self.status})>"


class LEDMaintenanceLog(Base):
    """Maintenance history and logs for installed screens."""

    __tablename__ = "oe_led_maintenance_log"

    led_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_led_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Maintenance details
    maintenance_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # preventive, corrective, emergency, inspection, calibration, cleaning
    
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="scheduled")
    # scheduled, in_progress, completed, cancelled
    
    # Schedule
    scheduled_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    completed_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # Team
    performed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    technician_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Work performed
    work_performed: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Parts used
    parts_replaced: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # [{part_name, quantity, cost, serial_number}]
    
    # Costs
    labor_cost: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parts_cost: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_cost: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    
    # Next maintenance
    next_maintenance_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    next_maintenance_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    led_project: Mapped[LEDProject] = relationship(back_populates="maintenance_logs")

    def __repr__(self) -> str:
        return f"<LEDMaintenanceLog {self.maintenance_type} - {self.title}>"


class LEDDocument(Base):
    """Digital documentation repository for LED projects."""

    __tablename__ = "oe_led_document"

    led_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_led_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Document details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # wiring_diagram, schematic, specification, manual, certificate, 
    # inspection_report, warranty, contract, photo, other
    
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # File reference
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    # Version
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    
    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    # active, archived, superseded
    
    # Dates
    document_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    uploaded_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # Author
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # External reference
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    led_project: Mapped[LEDProject] = relationship(back_populates="documents")

    def __repr__(self) -> str:
        return f"<LEDDocument {self.name} ({self.document_type})>"


class LEDBudget(Base):
    """Budget tracking for LED display projects."""

    __tablename__ = "oe_led_budget"

    led_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_led_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Budget category
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # hardware, labor, materials, transportation, installation, testing, 
    # commissioning, maintenance, contingency, other
    
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Budget amounts
    planned_amount: Mapped[str] = mapped_column(String(20), nullable=False, default="0")
    actual_amount: Mapped[str] = mapped_column(String(20), nullable=False, default="0")
    committed_amount: Mapped[str] = mapped_column(String(20), nullable=False, default="0")
    
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    
    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned")
    # planned, approved, in_progress, completed, over_budget
    
    # Breakdown
    breakdown: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # [{item, planned, actual, variance}]
    
    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    led_project: Mapped[LEDProject] = relationship(back_populates="budgets")

    def __repr__(self) -> str:
        return f"<LEDBudget {self.category}>"