# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Catalog resource ORM models.

Tables:
    oe_catalog_resource - curated resources (materials, equipment, labor, operators)
"""

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CatalogResource(Base):
    """A single catalog resource entry (material, equipment, labor, or operator)."""

    __tablename__ = "oe_catalog_resource"

    resource_code: Mapped[str] = mapped_column(
        String(100), index=True, nullable=False
    )  # Unique per region, not globally
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    resource_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # material, equipment, labor, operator
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # e.g. "Concrete & Cement", "Cranes"
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    base_price: Mapped[str] = mapped_column(String(50), nullable=False)  # Stored as string for SQLite compatibility
    min_price: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    max_price: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="cwicr_extraction"
    )  # cwicr_extraction, manual
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    specifications: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # ── Optional input-tax profile (issue #559) ─────────────────────────
    # All NULL = unclassified: no component tax is computed for the line.
    # ``tax_rate`` is a percentage string; ``tax_code`` names a registry row
    # (i18n_foundation TaxConfiguration.tax_code) resolved for the project's country.
    tax_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_rate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # taxable|exempt|out_of_scope
    price_includes_tax: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    input_tax_treatment: Mapped[str | None] = mapped_column(String(20), nullable=True)  # recoverable|cost_incorporated
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<CatalogResource {self.resource_code} "
            f"({self.resource_type}/{self.category} @ {self.base_price} {self.currency})>"
        )
