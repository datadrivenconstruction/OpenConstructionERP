"""Tables of the procurement take-off (R11). Built by the ERP's create_all, like the rest of the module."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class DesignProcurement(Base):
    """The take-off of a project: one BOQ that holds the quantities, one tender package per IFC class."""

    __tablename__ = "oe_design_procurement"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    boq_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # type_key: one line per element type; ifc_class: one line per IFC class. Fixed when the take-off is set up.
    group_by: Mapped[str] = mapped_column(String(16), nullable=False)
    # false: accepting a revision leaves the take-off as it is (the impact is still shown).
    follow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DesignTakeoffSection(Base):
    """An IFC class: a section of the take-off BOQ and the tender package raised over it."""

    __tablename__ = "oe_design_takeoff_section"
    __table_args__ = (UniqueConstraint("project_id", "ifc_class", name="uq_design_takeoff_section_class"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ifc_class: Mapped[str] = mapped_column(String(64), nullable=False)
    position_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    # Plain UUID: a person may delete the package in the tendering register; that shows as package_missing.
    package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DesignTakeoffLine(Base):
    """Position <-> element group, with what the model says beside what a person set."""

    __tablename__ = "oe_design_takeoff_line"
    __table_args__ = (UniqueConstraint("project_id", "group_key", name="uq_design_takeoff_line_group"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    ifc_class: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # length_m, area_m2, volume_m3, weight_kg, count
    basis: Mapped[str] = mapped_column(String(16), nullable=False)
    # false: basis comes from data/procurement/basis.json (a unit convention); true: a person chose it.
    basis_by_person: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    position_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # What the model gives now (decimal string), and what was last written to the position.
    model_quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_applied_quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    element_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    # Sum of every quantity key over the group, so a person can see the other bases: {key: {"sum", "elements"}}.
    available: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    # no_match, override, unpriced, lead_time_missing, no_quantity, partial_quantity, package_issued, position_deleted
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
