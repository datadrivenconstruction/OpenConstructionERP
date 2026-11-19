# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Central purchasing ORM models: one tender bundled over several projects.

A bundle belongs to the company, not to a project: the central buyer runs it,
each participating project carries its own share as its own commitment, on
its own cost line, under the legal entity that runs that project.

Tables:
    oe_central_purchasing_bundle  - the bundled tender and, once awarded, the award terms
    oe_central_purchasing_project - a project taking part, its entity and budget snapshot
    oe_central_purchasing_line    - one scope line of the bundle (trade or material item)
    oe_central_purchasing_share   - a project's quantity of one line, on that project's cost line
    oe_central_purchasing_split   - the award split, one row per project, with the document it drafted

The documents an award drafts are ordinary rows of ``oe_contracts_contract`` and
``oe_procurement_po``; their lines carry the share's ``cost_line_id``, which is
how each project's committed figure picks up its own share and nothing else.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

#: Bundle kinds: a subcontract drafts contracts, a supply drafts purchase orders.
KINDS = ("subcontract", "supply")
#: ``per_project_contracts``: one document per (project, entity). ``framework_call_off``: one
#: framework agreement per own legal entity, then call-offs from that entity's projects.
MODES = ("per_project_contracts", "framework_call_off")
STATUSES = ("draft", "published", "awarded", "cancelled")


class Bundle(Base):
    """A tender for one trade or material over several projects of the company."""

    __tablename__ = "oe_central_purchasing_bundle"
    __table_args__ = (UniqueConstraint("code", name="uq_oe_central_purchasing_bundle_code"),)

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="subcontract", server_default="subcontract")
    mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="per_project_contracts", server_default="per_project_contracts"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    #: Classification the line cost codes follow (``din276``, ``masterformat``, ``nrm1``...), from a pack.
    cost_code_standard: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Budget warning tolerance in percent; 0 warns on the first cent over.
    budget_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    #: Optional link to the bid package the tender ran in; the bundle works without one.
    bid_package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # Award terms. Rates live on the lines; either a discount or an agreed lump sum, never both.
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    lump_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    awarded_gross: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    awarded_net: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    awarded_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    awarded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    projects: Mapped[list[BundleProject]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="BundleProject.order_index"
    )
    lines: Mapped[list[BundleLine]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="BundleLine.order_index"
    )

    def __repr__(self) -> str:
        return f"<Bundle {self.code} {self.mode} {self.status}>"


class BundleProject(Base):
    """A project taking part in a bundle, with the entity that buys for it and its budget."""

    __tablename__ = "oe_central_purchasing_project"
    __table_args__ = (
        UniqueConstraint("bundle_id", "project_id", name="uq_oe_central_purchasing_project_bundle_project"),
        Index("ix_oe_central_purchasing_project_project", "project_id"),
    )

    bundle_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_central_purchasing_bundle.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    #: Copied from the project when it joins, so a later move of the project does not rewrite an award.
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    #: Snapshot of the planned budget on the share cost lines, or typed by the buyer.
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<BundleProject {self.project_id} in {self.bundle_id}>"


class BundleLine(Base):
    """One scope line: a trade item or material with the bundle quantity and the awarded rate."""

    __tablename__ = "oe_central_purchasing_line"

    bundle_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_central_purchasing_bundle.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    code: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    #: Awarded unit rate; empty until the award terms are entered.
    unit_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    #: Cost code in the bundle's standard (``342``, ``03 31 00``), used to find each project's cost line.
    cost_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    shares: Mapped[list[LineShare]] = relationship(cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<BundleLine {self.code} {self.quantity} {self.unit}>"


class LineShare(Base):
    """A project's quantity of one bundle line, booked on that project's cost line.

    ``quantity`` NULL means the buyer has not said yet (``bundle.project_share_missing``);
    zero means the project takes none of this line.
    """

    __tablename__ = "oe_central_purchasing_share"
    __table_args__ = (
        UniqueConstraint("line_id", "bundle_project_id", name="uq_oe_central_purchasing_share_line_project"),
    )

    line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_central_purchasing_line.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bundle_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_central_purchasing_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    #: That project's cost line; the money spine, never a BOQ position.
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<LineShare {self.quantity} of {self.line_id}>"


class AwardSplit(Base):
    """What one project carries of the award, and the document the award drafted for it."""

    __tablename__ = "oe_central_purchasing_split"
    __table_args__ = (UniqueConstraint("bundle_project_id", name="uq_oe_central_purchasing_split_project"),)

    bundle_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_central_purchasing_bundle.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bundle_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_central_purchasing_project.id", ondelete="CASCADE"), nullable=False
    )
    gross: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    discount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    net: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    #: ``contract`` | ``purchase_order`` | ``call_off_ceiling`` (framework mode: the entity's agreement).
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<AwardSplit {self.net} {self.document_type}>"
