"""Assembly ORM models.

Tables:
    oe_assemblies_assembly — composite cost items (calculations / recipes)
    oe_assemblies_component — individual line items within an assembly
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Assembly(Base):
    """A composite cost item built from cost database entries with factors.

    Example: "RC Wall C30/37 d=25cm" = concrete + rebar + formwork + labor,
    each with a factor that defines how much of the component is needed per
    unit of the assembly.
    """

    __tablename__ = "oe_assemblies_assembly"

    code: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    classification: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    total_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
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
    """A single line item within an assembly — links to a cost database entry."""

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
