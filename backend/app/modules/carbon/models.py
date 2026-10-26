# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Carbon & Sustainability ORM models.

Tables:
    oe_carbon_epd_record               - Environmental Product Declaration record
    oe_carbon_material_factor          - internal material carbon factor (with EPD link)
    oe_carbon_inventory                - project-level carbon inventory
    oe_carbon_embodied_entry           - embodied-carbon line in an inventory
    oe_carbon_scope1_entry             - direct-emission (fuel) line
    oe_carbon_scope2_entry             - purchased-energy line
    oe_carbon_scope3_entry             - upstream/downstream other line
    oe_carbon_operational_entry        - B6 use-phase operational-carbon line (6D Ph2)
    oe_carbon_lcc_entry                - ISO 15686-5 whole-life cost line (6D Ph2)
    oe_carbon_target                   - project carbon-reduction target
    oe_carbon_report                   - generated sustainability report

Notes:
    * cost_item_id and source_ref are plain UUID columns (no SQLAlchemy
      ForeignKey across module boundaries). Cross-module joins are
      handled in services.
"""

import uuid

from sqlalchemy import JSON, Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class EPDRecord(Base):
    """A single Environmental Product Declaration (EPD) record.

    Sourced from public databases (Ökobaudat, ICE, EC3) or imported manually.
    Stores GWP indicators per LCA module (A1-A3, A4, A5, B, C, D).
    """

    __tablename__ = "oe_carbon_epd_record"

    epd_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="custom", index=True)
    material_class: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(500), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str] = mapped_column(String(8), nullable=False, default="", index=True)
    declared_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="kg")

    gwp_a1a3: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    gwp_a4: Mapped[str | None] = mapped_column(Numeric(18, 6), nullable=True)
    gwp_a5: Mapped[str | None] = mapped_column(Numeric(18, 6), nullable=True)
    gwp_b_total: Mapped[str | None] = mapped_column(Numeric(18, 6), nullable=True)
    gwp_c_total: Mapped[str | None] = mapped_column(Numeric(18, 6), nullable=True)
    gwp_d_credits: Mapped[str | None] = mapped_column(Numeric(18, 6), nullable=True)

    validity_until: Mapped[str | None] = mapped_column(Date, nullable=True)
    document_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Supplier catalogue product this EPD declares (plain GUID, cross-module).
    supplier_catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    epd_format: Mapped[str | None] = mapped_column(String(16), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EPDRecord {self.epd_id} ({self.material_class}/{self.source})>"


class MaterialCarbonFactor(Base):
    """Internal-facing material carbon factor.

    Links a cost item (plain UUID - no FK across modules) to an EPD record
    or a manual override. Used when computing embodied carbon for BOQ
    positions that reference a cost item.
    """

    __tablename__ = "oe_carbon_material_factor"

    cost_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    epd_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_epd_record.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    manual_override_factor: Mapped[str | None] = mapped_column(Numeric(18, 6), nullable=True)
    unit_for_factor: Mapped[str] = mapped_column(String(20), nullable=False, default="kg")
    region: Mapped[str] = mapped_column(String(8), nullable=False, default="", index=True)
    last_reviewed_at: Mapped[str | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    # Published factor set this value comes from, and its year (outdated-set rule).
    factor_set: Mapped[str | None] = mapped_column(String(80), nullable=True)
    factor_set_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<MaterialCarbonFactor cost_item={self.cost_item_id} epd={self.epd_id}>"


class CarbonInventory(Base):
    """Project-level carbon inventory grouping embodied + operational entries."""

    __tablename__ = "oe_carbon_inventory"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Baseline inventory")
    scope: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="cradle_to_gate",
        index=True,
    )
    as_of_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)

    totals: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CarbonInventory {self.name} ({self.scope}/{self.status})>"


class EmbodiedCarbonEntry(Base):
    """A single embodied-carbon line in an inventory (A1-A5 stages)."""

    __tablename__ = "oe_carbon_embodied_entry"

    inventory_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    element_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Optional link to a BIM element (oe_bim_element.id). A plain GUID with NO
    # SQLAlchemy ForeignKey, matching the cross-module-ref convention used by
    # MaterialCarbonFactor.cost_item_id: refs into OTHER modules stay plain
    # GUID() columns so migration ordering across modules stays safe. When set,
    # the entry's quantity is derived from the model geometry rather than free
    # text. element_ref is kept for back-compat / display.
    element_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="kg")
    factor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_material_factor.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    factor_value_used: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    carbon_kg: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    stage: Mapped[str] = mapped_column(String(8), nullable=False, default="a1a3", index=True)
    # How this entry came to exist: 'manual' (typed in), 'auto_enriched'
    # (matched from a BIM element by auto_enrich_inventory_from_bim) or
    # 'boq_derived' (assigned from a BOQ position).
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="manual",
        server_default="manual",
    )
    # Confidence band of the auto-matched carbon factor (high|medium|low).
    # NULL for manually entered rows.
    match_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    data_quality: Mapped[str] = mapped_column(
        String(16), nullable=False, default="calculated", server_default="calculated"
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EmbodiedCarbonEntry {self.element_ref} ({self.stage}, {self.carbon_kg} kg)>"


class Scope1Entry(Base):
    """Direct (scope 1) emissions - on-site fuel combustion."""

    __tablename__ = "oe_carbon_scope1_entry"

    inventory_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[str] = mapped_column(Date, nullable=False)
    period_end: Mapped[str] = mapped_column(Date, nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(40), nullable=False, default="diesel", index=True)
    litres_or_m3: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    emission_factor_kg_co2e_per_unit: Mapped[str] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
    )
    total_co2e_kg: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="manual",
        index=True,
    )
    source_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    data_quality: Mapped[str] = mapped_column(
        String(16), nullable=False, default="calculated", server_default="calculated"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Scope1Entry {self.fuel_type} {self.total_co2e_kg} kgCO2e>"


class Scope2Entry(Base):
    """Indirect (scope 2) emissions - purchased energy."""

    __tablename__ = "oe_carbon_scope2_entry"

    inventory_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[str] = mapped_column(Date, nullable=False)
    period_end: Mapped[str] = mapped_column(Date, nullable=False)
    energy_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="grid_electricity",
        index=True,
    )
    kwh: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    emission_factor_kg_co2e_per_kwh: Mapped[str] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
    )
    market_or_location: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="location",
    )
    total_co2e_kg: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_quality: Mapped[str] = mapped_column(
        String(16), nullable=False, default="calculated", server_default="calculated"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Scope2Entry {self.energy_type} {self.kwh} kWh>"


class Scope3Entry(Base):
    """Other (scope 3) emissions - upstream/downstream transport, waste, travel."""

    __tablename__ = "oe_carbon_scope3_entry"

    inventory_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[str] = mapped_column(Date, nullable=False)
    period_end: Mapped[str] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="transport_upstream",
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    activity_data: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    activity_unit: Mapped[str] = mapped_column(String(40), nullable=False, default="tkm")
    emission_factor: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    total_co2e_kg: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    data_quality: Mapped[str] = mapped_column(
        String(16), nullable=False, default="calculated", server_default="calculated"
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Scope3Entry {self.category} {self.total_co2e_kg} kgCO2e>"


class OperationalCarbonEntry(Base):
    """B6 use-phase operational-carbon line (6D Phase 2).

    Recurring use-phase carbon from energy demand x a grid emission factor,
    rolled over a study period. One row per energy-consuming BIM asset (HVAC,
    lighting, pumps, lifts) or a single modelled whole-building line. Distinct
    from the Scope 1/2/3 corporate-GHG lines, which are period actuals, and from
    embodied A1-A5. ``carbon_kg`` is the study-period total (annual x years) and
    rolls into the EN 15978 B stage of the inventory total.

    AI-proposes / human-confirms: computed rows land as ``status='draft'`` with a
    ``match_confidence`` band and an ``assumptions`` note; a human confirms them.
    ``element_id`` is a plain GUID cross-module ref to ``oe_bim_element.id`` (no
    ForeignKey), matching the convention on ``EmbodiedCarbonEntry.element_id``.
    """

    __tablename__ = "oe_carbon_operational_entry"

    inventory_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    element_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    element_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    system: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="whole_building",
        server_default="whole_building",
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    end_use: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="regulated",
        server_default="regulated",
    )
    # How the annual energy was established: 'asset_info' / 'element' /
    # 'asset_power_rating' (per-asset signals) or 'modelled_intensity'
    # (gross floor area x an energy-use intensity).
    energy_source: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="modelled_intensity",
        server_default="modelled_intensity",
    )
    annual_energy_kwh: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    grid_country: Mapped[str] = mapped_column(String(8), nullable=False, default="", server_default="")
    grid_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grid_factor_kg_co2e_per_kwh: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    study_period_years: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    annual_carbon_kg: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    # Study-period total (annual_carbon_kg x study_period_years); the B6 figure.
    carbon_kg: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    stage: Mapped[str] = mapped_column(String(8), nullable=False, default="b6", server_default="b6")
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="modelled",
        server_default="modelled",
    )
    match_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )
    assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<OperationalCarbonEntry {self.system} {self.carbon_kg} kg ({self.status})>"


class LifeCycleCostEntry(Base):
    """ISO 15686-5 whole-life cost line (6D Phase 2).

    Whole-life cost of one element / system = capex + present value of opex +
    present value of the B4/B5 replacement cycle (keyed to service life and the
    study period) + present value of end-of-life. Future costs are discounted at
    ``discount_rate``; the four present-value components and the total are
    persisted for provenance so a stored row is fully reproducible.

    Sits side by side with the whole-life carbon rollup for the same inventory.
    AI-proposes / human-confirms: computed rows land as ``status='draft'`` with a
    ``confidence`` band and an ``assumptions`` note. ``element_id`` is a plain
    GUID cross-module ref to ``oe_bim_element.id`` (no ForeignKey).
    """

    __tablename__ = "oe_carbon_lcc_entry"

    inventory_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    element_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    element_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR", server_default="EUR")

    capex: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    annual_opex: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    replacement_cost: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    service_life_years: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    eol_cost: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    discount_rate: Mapped[str] = mapped_column(Numeric(9, 6), nullable=False, default=0)
    study_period_years: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")

    capex_pv: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    opex_pv: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    replacement_pv: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    replacement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    eol_pv: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    whole_life_cost: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)

    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="modelled",
        server_default="modelled",
    )
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )
    assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<LifeCycleCostEntry {self.category} {self.whole_life_cost} {self.currency} ({self.status})>"


class CarbonTarget(Base):
    """A project-level carbon-reduction target."""

    __tablename__ = "oe_carbon_target"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="absolute",
        index=True,
    )
    baseline_value: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    target_value: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    baseline_year: Mapped[int] = mapped_column(nullable=False, default=2020)
    target_year: Mapped[int] = mapped_column(nullable=False, default=2030)
    scope_set: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CarbonTarget {self.name} ({self.target_type}/{self.status})>"


class SustainabilityReport(Base):
    """A generated sustainability report under a chosen framework."""

    __tablename__ = "oe_carbon_report"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inventory_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_carbon_inventory.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    period_start: Mapped[str] = mapped_column(Date, nullable=False)
    period_end: Mapped[str] = mapped_column(Date, nullable=False)
    framework: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="ghg_protocol",
        index=True,
    )
    totals: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[str | None] = mapped_column(Date, nullable=True)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<SustainabilityReport project={self.project_id} framework={self.framework}>"


class GridEmissionFactor(Base):
    """Country / year grid emission factor for Scope 2 lookups.

    Sources: IEA Emissions Factors, DEFRA UK GHG Conversion Factors,
    EPA eGRID (US), Umweltbundesamt (DE). Stored as a static catalogue
    that callers query by ``(country_code, year)``.
    """

    __tablename__ = "oe_carbon_grid_factor"
    __table_args__ = (
        Index(
            "ix_oe_carbon_grid_factor_country_year",
            "country_code",
            "year",
            unique=True,
        ),
    )

    country_code: Mapped[str] = mapped_column(String(8), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    factor_kg_co2e_per_kwh: Mapped[str] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
    )
    method: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="location",
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return f"<GridEmissionFactor {self.country_code} {self.year} {self.factor_kg_co2e_per_kwh}>"


class CarbonCompanyActivity(Base):
    """Company-level GHG activity not tied to one project (fleet, offices, purchases).

    Feeds the CSRD / ESRS E1 aggregate next to the project inventories.
    ``scope`` is 1, 2 or 3 (GHG Protocol); ``scope3_category`` is 1-15.
    """

    __tablename__ = "oe_carbon_company_activity"

    reporting_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scope: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scope3_category: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="office")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    activity_amount: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    activity_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="kWh")
    emission_factor: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    factor_source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    co2e_kg: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    energy_kwh: Mapped[str] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    renewable_share_pct: Mapped[str] = mapped_column(Numeric(7, 3), nullable=False, default=0)
    market_based_co2e_kg: Mapped[str | None] = mapped_column(Numeric(18, 6), nullable=True)
    data_quality: Mapped[str] = mapped_column(String(16), nullable=False, default="calculated")
    source_module: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    source_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<CarbonCompanyActivity {self.reporting_year} s{self.scope} {self.co2e_kg} kg>"


class CarbonCompanyReport(Base):
    """A company-level climate report (ESRS E1, SECR, US state template).

    ``datapoints`` holds the computed figures; ``audit`` lists, per data point,
    every source record with its data-quality flag.
    """

    __tablename__ = "oe_carbon_company_report"

    reporting_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    template: Mapped[str] = mapped_column(String(32), nullable=False, default="esrs_e1", index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    net_revenue: Mapped[str] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    datapoints: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    audit: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<CarbonCompanyReport {self.template} {self.reporting_year}>"
