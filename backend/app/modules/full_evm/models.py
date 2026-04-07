"""Full EVM ORM models.

Tables:
    oe_evm_forecast — advanced EVM forecast records with ETC, EAC, VAC, TCPI
"""

import uuid

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class EVMForecast(Base):
    """Advanced EVM forecast with ETC, EAC, VAC, and TCPI metrics."""

    __tablename__ = "oe_evm_forecast"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    forecast_date: Mapped[str] = mapped_column(String(20), nullable=False)
    etc_: Mapped[str] = mapped_column(
        "etc",
        String(50),
        nullable=False,
        default="0",
    )
    eac: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    vac: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    tcpi: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    forecast_method: Mapped[str] = mapped_column(String(50), nullable=False, default="cpi")
    confidence_range_low: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence_range_high: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EVMForecast project={self.project_id} date={self.forecast_date}>"
