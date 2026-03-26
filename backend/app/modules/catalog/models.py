"""Catalog resource ORM models.

Tables:
    oe_catalog_resource — curated resources (materials, equipment, labor, operators)
"""

from sqlalchemy import Boolean, Integer, JSON, String, Text
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
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # e.g. "Concrete & Cement", "Cranes"
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    base_price: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # Stored as string for SQLite compatibility
    min_price: Mapped[str] = mapped_column(
        String(50), nullable=False, default="0"
    )
    max_price: Mapped[str] = mapped_column(
        String(50), nullable=False, default="0"
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="cwicr_extraction"
    )  # cwicr_extraction, manual
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    specifications: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
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
