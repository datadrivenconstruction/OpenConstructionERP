# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closeout ORM models.

Tables:
    oe_closeout_package - one closeout package per project (configurable checklist)
    oe_closeout_slot    - a single checklist requirement (as-built set, O&M, warranty, ...)
    oe_closeout_binding - links a slot to a CDE document / generated artifact / external URL
    oe_closeout_dossier - one assembled handover dossier (scope, checks, archive)
    oe_closeout_delivery - delivery log of a dossier (download, webhook, connector, email)
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

__all__ = ["CloseoutBinding", "CloseoutDelivery", "CloseoutDossier", "CloseoutPackage", "CloseoutSlot"]


class CloseoutPackage(Base):
    """A per-project digital handover / closeout package.

    One package per project (``project_id`` is unique). The checklist is
    seeded from a per-project-type template; completeness counters are kept
    denormalised on the row and recomputed by the service on every slot /
    binding mutation so the dashboard does not fan out aggregate queries.
    """

    __tablename__ = "oe_closeout_package"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Handover & Closeout Package")
    # residential / commercial / infrastructure / fitout / custom - drives the
    # default checklist seeded into the slots.
    project_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="commercial",
        server_default="commercial",
    )
    # draft / in_progress / ready / issued
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    checklist_template: Mapped[str] = mapped_column(String(60), nullable=False, default="commercial")

    # Denormalised completeness counters (kept in sync by the service).
    required_slot_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    delivered_slot_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    completeness_pct: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # Build result stamping.
    last_built_job_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    last_built_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Storage key of the last built ZIP (closeout/{project_id}/{package_id}.zip).
    package_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CloseoutPackage project={self.project_id} status={self.status} {self.completeness_pct}%>"


class CloseoutSlot(Base):
    """One checklist requirement inside a closeout package.

    Each slot is a thing the handover must deliver: an as-built drawing set,
    an O&M manual, a warranty, the COBie / asset register, punch-closure
    evidence, a final inspection certificate, the H&S file, and so on.
    """

    __tablename__ = "oe_closeout_slot"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_closeout_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stable key e.g. as_built_drawings / om_manual / warranty /
    # cobie_asset_register / punch_closure / final_inspection_cert / hs_file.
    slot_key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    # cde_document / generated / external_url / manual_upload
    source_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="cde_document",
        server_default="cde_document",
    )
    # cobie_xlsx / punch_closure_report / inspection_cert_pdf - tells the
    # builder what to render for a ``generated`` slot. NULL for document slots.
    generated_artifact: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Holds warranty expiry tracking when relevant
    # (warranty_starts / warranty_months / expiry_iso) so no numeric columns.
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CloseoutSlot {self.slot_key} ({self.category}) required={self.is_required}>"


class CloseoutBinding(Base):
    """Links a closeout slot to its evidence.

    ``document_id`` is a SOFT cross-link to ``oe_documents_document`` (not a
    hard FK) so deleting a document never cascade-wipes the closeout history -
    same convention as ``PunchItem.clash_result_id``. A slot may instead be
    backed by an external URL or a generated artifact (the slot's
    ``generated_artifact`` tells the builder what to render).
    """

    __tablename__ = "oe_closeout_binding"

    slot_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_closeout_slot.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Soft cross-link - NOT a hard FK (see class docstring).
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Human-confirmed the evidence is correct (a sign-off act).
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # AI-suggests-human-confirms: a suggested binding is recorded but never
    # auto-verified.
    suggested_by_ai: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    ai_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CloseoutBinding slot={self.slot_id} doc={self.document_id} verified={self.is_verified}>"


class CloseoutDossier(Base):
    """One assembled handover dossier of a package.

    A dossier is the package frozen for a recipient: a scope (whole project, one
    area or one asset), the completeness checks it was assembled against, and
    the archive it produced (index PDF + ZIP). The archive is filed as a
    document (``document_id``), so it shows in the documents hub and a share
    link can be minted for it; ``file_path`` is that document's file.
    ``status`` walks queued -> built -> delivered, or failed.
    """

    __tablename__ = "oe_closeout_dossier"
    __table_args__ = (Index("ix_closeout_dossier_package_created", "package_id", "created_at"),)

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_closeout_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", server_default="queued")
    # {"kind": "project" | "area" | "asset", "value": str | None}
    scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    check_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    check_results: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # The deliveries asked for when the dossier was requested, run after the build.
    delivery_request: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    built_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CloseoutDossier package={self.package_id} {self.status}>"


class CloseoutDelivery(Base):
    """One delivery attempt of a dossier: who it went to, how, and what came back.

    ``channel`` is download | webhook | connector | email. ``target_id`` names
    the integrations webhook endpoint or connector config used, ``recipient``
    an email address. ``resend_of`` links a resend to the attempt it repeats,
    so the log reads as a history rather than a set of unrelated rows.
    """

    __tablename__ = "oe_closeout_delivery"
    __table_args__ = (Index("ix_closeout_delivery_dossier_created", "dossier_id", "created_at"),)

    dossier_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_closeout_dossier.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    share_link_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    share_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    share_expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resend_of: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    delivered_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    delivered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CloseoutDelivery {self.channel} {self.status}>"
