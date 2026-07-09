"""Region-aware material/upah price models for the ACAP Batam price scraper.

Tables:
    oe_acap_region         — geographic regions (Batam, etc.)
    oe_acap_material_price — scraped price records with provenance
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Region(Base):
    """Geographic region — one row per scraped area."""

    __tablename__ = "oe_acap_region"

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    province: Mapped[str | None] = mapped_column(String(80), nullable=True)

    def __repr__(self) -> str:
        return f"<Region {self.code} — {self.name}>"


class MaterialPrice(Base):
    """Single scraped price record with full provenance tracking."""

    __tablename__ = "oe_acap_material_price"
    __table_args__ = (
        UniqueConstraint(
            "region_id", "source", "item_type", "item_name",
            name="uq_acap_price_region_source_item",
        ),
    )

    region_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_acap_region.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_name: Mapped[str] = mapped_column(String(160), nullable=False)
    satuan: Mapped[str | None] = mapped_column(String(40), nullable=True)
    price_min: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    price_max: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    extraction_method: Mapped[str] = mapped_column(String(30), nullable=False, default="selectolax")
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<MaterialPrice {self.item_type}:{self.item_name} [{self.source}]>"
