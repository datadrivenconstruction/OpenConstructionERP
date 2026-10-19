# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The EGS units a Saudi registration issues from, and the chain each one keeps.

ZATCA thinks in EGS units (e-invoice generation solutions): each unit has its
own key pair and its own cryptographic stamp identifier (CSID), and keeps its
own invoice counter (ICV) and previous-invoice-hash (PIH) chain. One clearance
registration (``oe_einvoice_clearance_profile``) can run several units, one per
branch or till; a document names the unit it was built on.

``oe_einvoice_zatca_egs_unit``
    Onboarding state, the certificates, and the head of the chain (last ICV,
    last hash). The builder takes this row ``FOR UPDATE`` while it allocates a
    counter, so two invoices built at once cannot share a counter or hash
    against the same predecessor. Secrets (the private key, the CSID secrets)
    are stored encrypted with :mod:`app.core.crypto`, and never leave the
    package: :func:`app.modules.einvoice_clearance.service.profile_as_dict`
    does not see this table.
``oe_einvoice_zatca_chain_entry``
    One row per allocated counter: which document took it and its hash. Unique
    on (unit, counter), so a gap or a repeat is a constraint failure, not a
    quiet fork of the chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

STATE_NEW = "new"
STATE_CSR_READY = "csr_ready"
STATE_COMPLIANCE_ISSUED = "compliance_issued"
STATE_COMPLIANCE_PASSED = "compliance_passed"
STATE_ACTIVE = "active"
STATE_REVOKED = "revoked"
STATES: tuple[str, ...] = (
    STATE_NEW,
    STATE_CSR_READY,
    STATE_COMPLIANCE_ISSUED,
    STATE_COMPLIANCE_PASSED,
    STATE_ACTIVE,
    STATE_REVOKED,
)


class ZatcaEgsUnit(Base):
    """One e-invoice generation solution unit, from onboarding to its last invoice."""

    __tablename__ = "oe_einvoice_zatca_egs_unit"
    __table_args__ = (
        UniqueConstraint("profile_id", "unit_key", name="uq_einvoice_zatca_egs_unit_profile_key"),
        Index("ix_einvoice_zatca_egs_unit_profile", "profile_id", "state"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_einvoice_clearance_profile.id", ondelete="CASCADE"),
        nullable=False,
    )
    # What the operator calls the unit; also the CSR's serial number part
    # ("1-<solution>|2-<version>|3-<unit>").
    unit_key: Mapped[str] = mapped_column(String(120), nullable=False)
    # The CSR subject and extension fields: organisation, branch, VAT number,
    # invoice types (four flags "1100"), location, industry. Plain data.
    csr_fields: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, default=STATE_NEW, server_default=STATE_NEW)
    # Which Fatoora environment the unit is onboarded on (data.ENVIRONMENTS).
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")

    # The unit's key pair. The private key is encrypted; a unit whose key lives
    # in an HSM or a signing service leaves it empty and names the signer.
    private_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    signer_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    signer_config: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    csr_pem: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    # The compliance CSID and then the production CSID. The token is the
    # certificate (base64 of base64 DER) and is not secret; the secret is.
    compliance_request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    compliance_token: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    compliance_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    production_request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    production_token: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    production_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    certificate_not_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The compliance invoices ZATCA asks for before it issues a production
    # CSID, by document kind, with ZATCA's verdict on each.
    compliance_results: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )

    # The head of the chain: the counter and hash of the last document built.
    last_icv: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")

    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<ZatcaEgsUnit {self.unit_key} {self.state} icv={self.last_icv}>"


class ZatcaChainEntry(Base):
    """One counter of one unit: the document that took it and its hash."""

    __tablename__ = "oe_einvoice_zatca_chain_entry"
    __table_args__ = (
        UniqueConstraint("unit_id", "icv", name="uq_einvoice_zatca_chain_entry_unit_icv"),
        Index("ix_einvoice_zatca_chain_entry_uuid", "invoice_uuid", unique=True),
    )

    unit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_einvoice_zatca_egs_unit.id", ondelete="CASCADE"),
        nullable=False,
    )
    icv: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    previous_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    invoice_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    type_code: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    subtype: Mapped[str] = mapped_column(String(7), nullable=False, default="", server_default="")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ZatcaChainEntry unit={self.unit_id} icv={self.icv}>"


__all__ = [
    "STATES",
    "STATE_ACTIVE",
    "STATE_COMPLIANCE_ISSUED",
    "STATE_COMPLIANCE_PASSED",
    "STATE_CSR_READY",
    "STATE_NEW",
    "STATE_REVOKED",
    "ZatcaChainEntry",
    "ZatcaEgsUnit",
]
