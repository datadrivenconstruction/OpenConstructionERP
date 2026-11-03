# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SCIM ORM models.

Tables:
    oe_scim_group - groups pushed by the IdP; an admin may map one to a role
    oe_scim_group_member - group membership (group, user)
"""

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ScimGroup(Base):
    """A group from the IdP. ``role`` is set by an admin only; NULL means cosmetic."""

    __tablename__ = "oe_scim_group"

    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return f"<ScimGroup {self.display_name} ({self.role})>"


scim_group_member = Table(
    "oe_scim_group_member",
    Base.metadata,
    Column(
        "group_id",
        GUID(),
        ForeignKey("oe_scim_group.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

__all__ = ["ScimGroup", "scim_group_member"]
