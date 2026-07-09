"""AHSP coefficient ORM models.

Tables:
    oe_acap_ahsp_coefficient — one row per unique AHSP item (by kode)
    oe_acap_ahsp_resource    — bahan/tenaga/alat child rows for each coefficient
"""

import uuid

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class AhspCoefficient(Base):
    """AHSP coefficient — one per unique construction work item."""

    __tablename__ = "oe_acap_ahsp_coefficient"

    kode: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    uraian: Mapped[str] = mapped_column(Text, nullable=False)
    satuan: Mapped[str] = mapped_column(String(20), nullable=False)
    kategori: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    referensi: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    referensi_kode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sumber: Mapped[str] = mapped_column(Text, nullable=False, default="")

    resources: Mapped[list["AhspResource"]] = relationship(
        back_populates="coefficient",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AhspCoefficient {self.kode}>"


class AhspResource(Base):
    """Single resource row (bahan/tenaga/alat) for an AHSP coefficient."""

    __tablename__ = "oe_acap_ahsp_resource"

    coefficient_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_acap_ahsp_coefficient.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tipe: Mapped[str] = mapped_column(String(10), nullable=False)
    nama: Mapped[str] = mapped_column(String(120), nullable=False)
    satuan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    koef: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)

    coefficient: Mapped[AhspCoefficient] = relationship(back_populates="resources")

    def __repr__(self) -> str:
        return f"<AhspResource {self.tipe}:{self.nama} koef={self.koef}>"
