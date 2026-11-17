# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out ORM models.

Tables:
    oe_setting_out_tolerance_profile - a project's own tolerance profile
        (item type -> horizontal/vertical mm). Demo and pack profiles live in code.
    oe_setting_out_request - one stakeout request: what to set out (linked BOQ
        position, BIM or CAD element), the tolerance it is checked against
        (snapshot, so a later profile edit never rewrites a verdict), an
        optional alignment, and the instrument/control defaults for the crew.
    oe_setting_out_point - one design stake of a request (E, N, Z, chainage/offset).
    oe_setting_out_record - one measurement of a stake. Append-only: the newest
        record is the stake's state, older ones are its history.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SettingOutToleranceProfile(Base):
    """A tolerance profile a project defined for itself."""

    __tablename__ = "oe_setting_out_tolerance_profile"
    __table_args__ = (Index("ix_oe_setting_out_tolerance_profile_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # {item_type | "default": {"h_mm": float, "v_mm": float | null}}
    items: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reference: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SettingOutRequest(Base):
    """What to set out, and against which tolerance."""

    __tablename__ = "oe_setting_out_request"
    __table_args__ = (Index("ix_oe_setting_out_request_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other", server_default="other")
    # "demo" | "pack:<..>" | "project:<uuid>" | "" (no profile)
    tolerance_key: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    tolerance_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    tolerance_source: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    tol_h_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    tol_v_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    # boq | bim | cad | "" - the element this request sets out
    element_ref_type: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    element_ref_id: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    element_ref_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    alignment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    instrument: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    control_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SettingOutPoint(Base):
    """One design stake."""

    __tablename__ = "oe_setting_out_point"
    __table_args__ = (Index("ix_oe_setting_out_point_request", "request_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_setting_out_request.id", ondelete="CASCADE"), nullable=False
    )
    point_id: Mapped[str] = mapped_column(String(64), nullable=False)
    design_e: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    design_n: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    design_z: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    chainage: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    offset_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class SettingOutRecord(Base):
    """One measurement of a stake, with its deltas and verdict as computed then."""

    __tablename__ = "oe_setting_out_record"
    __table_args__ = (
        Index("ix_oe_setting_out_record_point", "point_id"),
        Index("ix_oe_setting_out_record_request", "request_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_setting_out_request.id", ondelete="CASCADE"), nullable=False
    )
    point_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_setting_out_point.id", ondelete="CASCADE"), nullable=False
    )
    measured_e: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    measured_n: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    measured_z: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    de_mm: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    dn_mm: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    d_mm: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    dz_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 1), nullable=True)
    tol_h_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    tol_v_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    # pass | fail | no_tolerance
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    control_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    measured_by: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    measured_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    ncr_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
