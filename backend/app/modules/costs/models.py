"""Cost item ORM models.

Tables:
    oe_costs_item — cost database entries (CWICR, RSMeans, BKI, custom)
"""

from sqlalchemy import JSON, Boolean, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CostItem(Base):
    """A single cost database entry (rate, unit price, assembly component)."""

    __tablename__ = "oe_costs_item"
    __table_args__ = (
        UniqueConstraint("code", "region", name="uq_costs_code_region"),
        # Indexes for common filter combinations in search()
        Index("ix_costs_source_region", "source", "region"),
        Index("ix_costs_is_active", "is_active"),
    )

    code: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    descriptions: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    rate: Mapped[str] = mapped_column(String(50), nullable=False)  # Stored as string for SQLite compatibility
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="cwicr", index=True)  # cwicr, rsmeans, bki, custom
    classification: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    components: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    region: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CostItem {self.code} ({self.unit} @ {self.rate} {self.currency})>"
