# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠E-signature registry ORM models.

Tables:
    oe_signing_session - a signing session: one document (referenced by an
        opaque ``document_ref`` that points at a file or record living in
        another module) that a set of named signatories must sign at a given
        legal capability. Carries the workflow ``status`` and an optional
        expiry.
    oe_signing_signature - a single signature *attestation* recorded against a
        session: who signed, in what role, at what time, against which content
        hash, with which certificate *metadata*. Never a key, never a password.

Design
======
- Tenancy is by ``project_id`` (non-null, cascade delete) on both tables, so the
  same ``verify_project_access`` guard applies and a cross-project id surfaces as
  404. ``project_id`` is duplicated onto the signature row (denormalised from its
  session) so authority checks and project-wide queries - the expiring-certs
  sweep - do not need a join.
- Every code field is an open-ended ``String`` (never a DB enum) so a provider
  pack can introduce a new capability or status without a migration; the API
  validates against the built-in whitelist.
- ``document_content_hash`` is a plain hex string the caller computes over the
  signed content (this module never opens the document). A signature also stores
  the ``content_hash`` it actually signed, so a later change to the session's
  content hash makes the earlier signatures detectably stale (delta-by-hash).
- No cryptographic material is modelled. ``cert_subject`` / ``cert_valid_until``
  are descriptive metadata copied from a certificate, not the certificate.
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SigningSession(Base):
    """A document signing workflow: signatories, capability and status."""

    __tablename__ = "oe_signing_session"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── The signed thing ───────────────────────────────────────────────
    # An opaque reference to the document living elsewhere (a compliance doc,
    # a transmittal, a contract record). This module never opens it.
    document_ref: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Caller-supplied sha256 hex of the content to be signed. The signature
    # attestations record which hash they actually signed, so a change here
    # marks the earlier signatures stale.
    document_content_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    # ── Legal capability (never a vendor / brand) ──────────────────────
    # qualified_electronic | advanced_electronic | simple_electronic |
    # digital_certificate.
    provider_capability: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        default="simple_electronic",
        server_default="simple_electronic",
        index=True,
    )

    # What the provider registry actually handed back the last time this
    # session's status was derived, taken from the resolved provider's own
    # ``capability``. It is deliberately NOT "the capability that produced the
    # attestations already recorded": no adapter can be swapped in mid-session
    # today, but if one ever is, this field moves with the resolver and the
    # older attestations keep whatever they were signed under.
    #
    # ``provider_capability`` above is what the caller REQUIRES. Core ships one
    # provider, which delivers ``simple_electronic`` and performs no
    # cryptography, so a session requiring a stronger tier resolves to it and
    # records the difference here instead of claiming the requirement was met.
    # NULL means no derivation has stamped it yet (every row written before
    # this column existed) - it must never be read as "same as required".
    delivered_capability: Mapped[str | None] = mapped_column(
        String(48),
        nullable=True,
        default=None,
    )

    # ── Who must sign ──────────────────────────────────────────────────
    # A list of {name, role, required} dicts. ``role`` is the key the signature
    # attestations are matched against; ``required`` gates whether the session
    # can reach fully_signed without it.
    signatory_map: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # ── Workflow status (recomputed on every attestation) ──────────────
    # draft | awaiting_signatures | partially_signed | fully_signed |
    # declined | expired.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<SigningSession ref={self.document_ref[:40]!r} "
            f"required={self.provider_capability} delivered={self.delivered_capability} "
            f"status={self.status}>"
        )


class Signature(Base):
    """A single recorded signature attestation against a session."""

    __tablename__ = "oe_signing_signature"

    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_signing_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the session so project-scoped authority checks and the
    # expiring-certs sweep run without a join.
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    signatory_name: Mapped[str] = mapped_column(String(255), nullable=False)
    signatory_role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # ── Certificate metadata (descriptive, never the certificate) ──────
    cert_subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cert_valid_until: Mapped[_date | None] = mapped_column(Date, nullable=True, index=True)

    # The content hash this signatory actually signed. Compared against the
    # session's current document_content_hash to detect a stale signature.
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    # signed | declined.
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="signed",
        server_default="signed",
        index=True,
    )

    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<Signature session={self.session_id} role={self.signatory_role!r} status={self.status}>"


__all__ = ["Signature", "SigningSession"]
