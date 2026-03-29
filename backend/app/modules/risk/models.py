"""Risk Register ORM models.

Tables:
    oe_risk_register — risk items with probability, impact, mitigation, and status
"""

import uuid

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class RiskItem(Base):
    """Risk register entry tracking project risks and mitigation."""

    __tablename__ = "oe_risk_register"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="technical"
    )
    probability: Mapped[str] = mapped_column(String(10), nullable=False, default="0.5")
    impact_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    impact_schedule_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    impact_severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium"
    )
    risk_score: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="identified")
    mitigation_strategy: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contingency_plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    response_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<RiskItem {self.code} — {self.title[:40]} ({self.status})>"
