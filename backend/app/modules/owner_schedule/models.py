# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule ORM models.

Tables:
    oe_owner_schedule_profile - a format profile saved by a user from the mapping wizard.
    oe_owner_schedule         - one owner schedule linked to one BOQ: the profile used,
                                the owner's latest file (the export template) and its revision.
    oe_owner_schedule_item    - one owner pay item as the owner wrote it (immutable owner
                                reference) and the BOQ position that prices it.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class OwnerScheduleProfile(Base):
    """A user-defined owner format profile."""

    __tablename__ = "oe_owner_schedule_profile"
    __table_args__ = (UniqueConstraint("key", name="uq_owner_schedule_profile_key"),)

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class OwnerSchedule(Base):
    """An owner's bid schedule attached to a BOQ."""

    __tablename__ = "oe_owner_schedule"
    __table_args__ = (UniqueConstraint("boq_id", name="uq_owner_schedule_boq"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_boq_boq.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_key: Mapped[str] = mapped_column(String(80), nullable=False)
    # Snapshot of the profile used, so a later edit of the profile cannot change an export.
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class OwnerScheduleItem(Base):
    """One owner pay item. Owner fields are never edited by pricing; only an applied addendum changes them."""

    __tablename__ = "oe_owner_schedule_item"
    __table_args__ = (UniqueConstraint("schedule_id", "item_no", name="uq_owner_schedule_item_no"),)

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_owner_schedule.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    item_no: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    is_section: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_alternate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_lump_sum: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_boq_position.id", ondelete="SET NULL"), nullable=True, index=True
    )
