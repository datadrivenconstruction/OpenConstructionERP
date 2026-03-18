"""Project ORM models.

Tables:
    oe_projects_project — construction estimation projects
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Project(Base):
    """Construction estimation project."""

    __tablename__ = "oe_projects_project"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    region: Mapped[str] = mapped_column(String(50), nullable=False, default="DACH")
    classification_standard: Mapped[str] = mapped_column(
        String(50), nullable=False, default="din276"
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="de")
    validation_rule_sets: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=lambda: ["boq_quality"],
        server_default='["boq_quality"]',
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Project {self.name} ({self.status})>"
