# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠E-invoice clearance ORM models.

Tables:
    oe_einvoice_clearance_profile  - how one legal entity is registered in one
        country: the regime, the tax registration, the network participant id,
        the certificate the platform signs with, and whether it is pointed at a
        sandbox.
    oe_einvoice_clearance_document - one invoice on its way through a country's
        platform: what was submitted, what came back, and where it now stands.
    oe_einvoice_clearance_event    - the append-only trail behind that status.

No ``relationship()`` is declared. Everything here is reached by id from the
service, so there is no lazy-loading strategy to choose and no
``MissingGreenlet`` to avoid.

Foreign keys
============
Only the two intra-module links are foreign keys. ``project_id`` and
``invoice_id`` are plain ``GUID`` columns, which is what ``finance.Invoice``
itself does with ``project_id`` and ``source_claim_id``. It also happens to be
the right answer here for a second reason: a cleared document is a fiscal
record whose counterpart is held by a tax authority, and deleting our copy of an
invoice must not delete the record of the identifier that authority issued.

The two intra-module foreign keys carry explicit names. Under the metadata
naming convention the generated name would be over the 63-byte PostgreSQL limit
and would be truncated with a hash, which is deterministic but leaves the
``create_all`` schema and the migration disagreeing about a constraint name for
no reason.

Nothing is ever queried *inside* ``country_fields`` or ``raw_response``. On
PostgreSQL a ``.contains()`` on a JSON column compiles to a string LIKE rather
than to JSONB containment, so a filter written that way would quietly mean
something else. Filtering is on real columns only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base

# ── Status machine ───────────────────────────────────────────────────────────
#
# Eight states are the same for every regime; the ninth exists because network
# exchange has no authority to clear anything. Forcing a routed Peppol document
# into ``cleared`` would tell a reader an authority answered for it, and forcing
# it into ``reported`` would tell them a tax filing happened. Neither did.

STATUS_DRAFT = "draft"
STATUS_VALIDATED = "validated"
STATUS_QUEUED = "queued"
STATUS_SUBMITTED = "submitted"
STATUS_CLEARED = "cleared"
STATUS_REPORTED = "reported"
STATUS_DELIVERED = "delivered"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"

DOCUMENT_STATUSES: tuple[str, ...] = (
    STATUS_DRAFT,
    STATUS_VALIDATED,
    STATUS_QUEUED,
    STATUS_SUBMITTED,
    STATUS_CLEARED,
    STATUS_REPORTED,
    STATUS_DELIVERED,
    STATUS_REJECTED,
    STATUS_CANCELLED,
)

# The terminal success state per regime. This is the whole reason the regime is
# stored on the document: an adapter reports "the platform accepted it" and the
# regime decides what accepting it meant.
TERMINAL_SUCCESS: dict[str, str] = {
    "clearance": STATUS_CLEARED,
    "reporting": STATUS_REPORTED,
    "network": STATUS_DELIVERED,
}

# States from which nothing further happens without a new document.
FINAL_STATUSES: frozenset[str] = frozenset({STATUS_CLEARED, STATUS_REPORTED, STATUS_DELIVERED, STATUS_CANCELLED})

# States in which the authority has answered and the document is now a record of
# something that happened outside this system. Editing one of these is the thing
# the ``cleared_immutable`` rule refuses.
SETTLED_STATUSES: frozenset[str] = frozenset(
    {STATUS_SUBMITTED, STATUS_CLEARED, STATUS_REPORTED, STATUS_DELIVERED, STATUS_CANCELLED}
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_DRAFT: frozenset({STATUS_VALIDATED, STATUS_QUEUED, STATUS_SUBMITTED}),
    STATUS_VALIDATED: frozenset({STATUS_DRAFT, STATUS_QUEUED, STATUS_SUBMITTED}),
    STATUS_QUEUED: frozenset({STATUS_SUBMITTED, STATUS_REJECTED, STATUS_DRAFT}),
    STATUS_SUBMITTED: frozenset({STATUS_CLEARED, STATUS_REPORTED, STATUS_DELIVERED, STATUS_REJECTED}),
    # A rejection is fixed on the same document and resubmitted; the retry count
    # is what tells an operator this is the fourth attempt at the same invoice.
    STATUS_REJECTED: frozenset({STATUS_DRAFT, STATUS_VALIDATED, STATUS_QUEUED, STATUS_SUBMITTED}),
    # Cancellation is an act against the authority, so it is only reachable from
    # a state where the authority has something to cancel. Abandoning a draft is
    # a delete, not a cancellation, and calling both "cancelled" would put
    # documents that never existed for the tax office in the same bucket as ones
    # that were withdrawn from it.
    STATUS_CLEARED: frozenset({STATUS_CANCELLED}),
    STATUS_REPORTED: frozenset({STATUS_CANCELLED}),
    STATUS_DELIVERED: frozenset({STATUS_CANCELLED}),
    STATUS_CANCELLED: frozenset(),
}

# What an event records. ``note`` is the manual entry an operator adds when they
# phoned the provider; everything else is written by the state machine.
EVENT_TYPES: tuple[str, ...] = (
    "created",
    "updated",
    "validated",
    "queued",
    "submitted",
    "cleared",
    "reported",
    "delivered",
    "rejected",
    "cancelled",
    "note",
)


def can_transition(from_status: str, to_status: str) -> bool:
    """Whether the machine allows this move. Unknown states move nowhere."""
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def can_be_sent(from_status: str) -> bool:
    """Whether sending a document in this state could get anywhere.

    Read off the transition table rather than kept as a second list of statuses,
    so the check a caller makes up front and the one the move itself makes can
    never drift apart. A queued document counts, because re-driving a stuck
    queue is not a state change. A submitted one does not: it has already gone,
    and sending it again is how one sale ends up with two cleared invoices.
    """
    return from_status == STATUS_QUEUED or can_transition(from_status, STATUS_QUEUED)


class EInvoiceProfile(Base):
    """How one legal entity is registered with one country's platform.

    ``company_key`` is free text, not a foreign key, because the platform has no
    company table - one deployment is one company - while a group that invoices
    from two legal entities in the same country needs two registrations. The key
    is whatever the operator calls the entity: a VAT id, a short name, a code
    from their accounting system.

    ``sandbox`` defaults to true on purpose. A profile somebody created and did
    not finish configuring must not be able to mint records that look like live
    fiscal identifiers, and the offline reference adapter refuses to serve a live
    profile at all.
    """

    __tablename__ = "oe_einvoice_clearance_profile"
    __table_args__ = (
        UniqueConstraint(
            "company_key",
            "country",
            name="uq_einvoice_clearance_profile_company_country",
        ),
        Index("ix_einvoice_clearance_profile_country", "country", "is_active"),
    )

    # The legal entity that issues under this registration.
    company_key: Mapped[str] = mapped_column(String(120), nullable=False)
    # ISO 3166-1 alpha-2. Stored upper-cased by the schema layer.
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    # Denormalised from the country registry so a row still reads correctly if
    # the registry later reclassifies a country - the profile records what the
    # operator registered under, not what the code believes today.
    regime: Mapped[str] = mapped_column(String(16), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    # The tax registration the authority knows this entity by: RFC, CNPJ,
    # partita IVA, NIP, CUI, VAT number, GSTIN.
    tax_registration_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    # The address on the exchange network: a Peppol participant id, a codice
    # destinatario, a Leitweg-ID routing target.
    network_participant_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    # A *reference* to the signing certificate, never the certificate and never
    # a key. Where the key lives is the deployment's business; this column names
    # it so an operator can tell which one a submission used.
    certificate_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")

    # Which adapter serves this profile. Empty means none is configured and a
    # submission is refused rather than silently routed somewhere.
    adapter_key: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    # Adapter-specific configuration that is not a credential: endpoint names,
    # a provider's account reference, a series prefix.
    settings: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        mode = "sandbox" if self.sandbox else "live"
        return f"<EInvoiceProfile {self.company_key}/{self.country} {self.regime} {mode}>"


class EInvoiceDocument(Base):
    """One invoice on its way through a country's platform.

    The document is not the invoice. The invoice is a finance row that may be
    edited, credited and reissued; this is the record of one attempt to put one
    exact payload through one country's platform, and once the platform has
    answered it stops being editable.

    ``payload_hash`` is a SHA-256 of the exact bytes submitted, which is what
    makes "the same payload may not go twice" a checkable statement rather than
    a hope. It also dates the payload: an invoice edited after clearance no
    longer hashes to what the authority holds.
    """

    __tablename__ = "oe_einvoice_clearance_document"
    __table_args__ = (
        Index("ix_einvoice_clearance_document_invoice", "invoice_id"),
        Index("ix_einvoice_clearance_document_country_status", "country", "status"),
        # The lookup behind the duplicate-payload rule. Deliberately not unique:
        # whether the same content may go again is a business decision the rule
        # makes with the earlier document in hand, and a unique constraint would
        # turn that decision into an IntegrityError nobody can explain to an
        # accountant.
        Index("ix_einvoice_clearance_document_payload_hash", "payload_hash"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # The finance invoice this document represents. Plain GUID, no foreign key -
    # see the module docstring: the fiscal record outlives the invoice row.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_einvoice_clearance_profile.id",
            ondelete="RESTRICT",
            name="fk_einvoice_clearance_document_profile",
        ),
        nullable=False,
        index=True,
    )

    country: Mapped[str] = mapped_column(String(2), nullable=False)
    regime: Mapped[str] = mapped_column(String(16), nullable=False)
    # The national format key from the country registry, denormalised for the
    # same reason as ``regime``.
    document_format: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    # What the invoice says, carried here so the record stands on its own after
    # the invoice row has moved on. Currency is explicit per row: an amount
    # without one is meaningless in a module whose entire subject is countries.
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    invoice_date: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    total_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))

    # The exact document that goes to the platform, kept because the record is
    # otherwise unanswerable: "show me what we actually sent" is the first
    # question in every dispute with an authority, and a hash alone can confirm
    # a guess but cannot produce the document. Same call
    # ``authority_submission.Submission.generated_xml`` makes.
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    payload_media_type: Mapped[str] = mapped_column(
        String(80), nullable=False, default="application/xml", server_default="application/xml"
    )
    payload_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # National fields EN 16931 has no place for: an RFC and a Uso CFDI, a CFOP
    # and an NCM, a codice destinatario. Read in Python only.
    country_fields: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=STATUS_DRAFT, server_default=STATUS_DRAFT, index=True
    )
    # What the authority gave back: a UUID, a chave de acesso, a protocol
    # number, a KSeF number, an IRN, a transmission id.
    authority_identifier: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The authority's own rejection code, kept verbatim. This is the string an
    # accountant will be asked about by name - "why did we get a CFDI40102" -
    # and a paraphrase of it is worth nothing to them.
    rejection_code: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    rejection_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cancellation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Which adapter actually handled it, copied off the profile at submission so
    # a later reconfiguration cannot rewrite history.
    adapter_key: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return (
            f"<EInvoiceDocument {self.country}/{self.regime} {self.invoice_number} "
            f"{self.status} id={self.authority_identifier or '-'}>"
        )


class EInvoiceEvent(Base):
    """One entry in a document's append-only trail.

    Append-only is the point. When an authority rejects a document at 02:00 and
    accepts the corrected one at 09:00, the rejection is the part somebody will
    need six months later, and a status column alone has already forgotten it.
    Nothing in this module updates or deletes an event; the only write is an
    insert, and rows go only when the document goes.
    """

    __tablename__ = "oe_einvoice_clearance_event"
    __table_args__ = (Index("ix_einvoice_clearance_event_document_seq", "document_id", "sequence"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_einvoice_clearance_document.id",
            ondelete="CASCADE",
            name="fk_einvoice_clearance_event_document",
        ),
        nullable=False,
    )
    # Monotonic per document. ``created_at`` alone cannot order two events
    # written inside one transaction, and the order of a submission and its
    # rejection is exactly what a reader needs.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str] = mapped_column(String(24), nullable=False, default="", server_default="")
    to_status: Mapped[str] = mapped_column(String(24), nullable=False, default="", server_default="")

    message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # The authority's code on this event, so a rejection is greppable by the
    # code the accountant was quoted rather than by prose.
    authority_code: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    # Whatever the adapter got back, stored as given. When a provider changes a
    # response shape this is the only record of what the old one looked like.
    raw_response: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<EInvoiceEvent {self.document_id} #{self.sequence} {self.event_type}>"


__all__ = [
    "ALLOWED_TRANSITIONS",
    "DOCUMENT_STATUSES",
    "EVENT_TYPES",
    "FINAL_STATUSES",
    "SETTLED_STATUSES",
    "STATUS_CANCELLED",
    "STATUS_CLEARED",
    "STATUS_DELIVERED",
    "STATUS_DRAFT",
    "STATUS_QUEUED",
    "STATUS_REJECTED",
    "STATUS_REPORTED",
    "STATUS_SUBMITTED",
    "STATUS_VALIDATED",
    "TERMINAL_SUCCESS",
    "EInvoiceDocument",
    "EInvoiceEvent",
    "EInvoiceProfile",
    "can_be_sent",
    "can_transition",
]
