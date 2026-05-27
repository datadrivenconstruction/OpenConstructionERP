"""‌⁠‍Assembly ORM models.

Tables:
    oe_assemblies_assembly — composite cost items (calculations / recipes)
    oe_assemblies_component — individual line items within an assembly
    oe_assemblies_template  — platform-wide canonical templates (v3.13.0
        Assembly Library) — read-only, catalogue-agnostic recipes that
        match against the project's bound cost catalogue at apply time.
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Assembly(Base):
    """‌⁠‍A composite cost item built from cost database entries with factors.

    Example: "RC Wall C30/37 d=25cm" = concrete + rebar + formwork + labor,
    each with a factor that defines how much of the component is needed per
    unit of the assembly.
    """

    __tablename__ = "oe_assemblies_assembly"

    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    classification: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    total_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    bid_factor: Mapped[str] = mapped_column(String(10), nullable=False, default="1.0")
    regional_factors: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    components: Mapped[list["Component"]] = relationship(
        back_populates="assembly",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Component.sort_order",
    )

    def __repr__(self) -> str:
        return f"<Assembly {self.code} — {self.name[:40]}>"


class Component(Base):
    """‌⁠‍A single line item within an assembly — links to a cost database entry."""

    __tablename__ = "oe_assemblies_component"

    assembly_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_assemblies_assembly.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cost_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_costs_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    catalog_resource_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_catalog_resource.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Link to catalog resource (material, equipment, labor)",
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    # First-class resource_type ("material" / "labor" / "equipment" /
    # "operator" / "subcontractor" / "overhead"). Promoted from metadata
    # in v2940 — see migration for back-fill rules. Nullable because
    # legacy rows may still be untyped until a user revisits them.
    resource_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    factor: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0")
    quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0")
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    total: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    assembly: Mapped[Assembly] = relationship(back_populates="components")

    def __repr__(self) -> str:
        return f"<Component {self.description[:40]} (factor={self.factor})>"


class AssemblyTemplate(Base):
    """A canonical, platform-wide assembly template (Assembly Library, v3.13.0).

    Templates are read-only for end users — they are the starting points
    estimators clone or apply to a BOQ. Each component is defined by a
    catalogue-agnostic ``cost_match_query`` (free text such as
    "concrete C30/37 ready-mix") that the apply endpoint resolves against
    the project's bound cost catalogue at runtime via the existing
    ``costs.matcher`` lexical search. That keeps the seed independent of
    any single supplier / region / code-list / currency.

    Columns
    -------
    name
        Canonical English name. Unique — the seeder upserts by this key.
    name_translations
        JSON dict ``{lang: localised_name}``. The first slice ships DE +
        RU + ES; more languages join in subsequent slices.
    category
        Coarse bucket (``concrete`` | ``masonry`` | ``drywall`` | ``mep`` |
        ``roofing`` | ``insulation`` | ``finishing`` | ``earthwork`` |
        ``steel``). Used to drive the library's category-chip filter.
    unit
        Output unit of the recipe (m³, m², m, kg, pcs, lsum, set, h).
    components
        JSON list of component dicts. See ``templates_seed`` for the
        contract.
    classification
        JSON ``{"din276": "...", "masterformat": "..."}`` — the recipe's
        cost-classification anchor used by the BOQ side for grouping
        and validation.
    tags
        JSON list of free-text tags. Searchable.
    is_builtin
        ``True`` for rows shipped by the platform seed; ``False`` for
        future user-contributed templates (next slice).
    """

    __tablename__ = "oe_assemblies_template"

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name_translations: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    components: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    classification: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    def __repr__(self) -> str:
        return f"<AssemblyTemplate {self.name[:60]} ({self.category}/{self.unit})>"
