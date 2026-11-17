# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed estimate ORM models.

Tables:
    oe_estimate_archive_seal        - one sealed estimate; content columns never change
    oe_estimate_archive_attachment  - a file included in the seal and its hash at seal time
    oe_estimate_archive_receipt     - the counterparty's acknowledgement of the fingerprint
    oe_estimate_archive_opening     - one recorded opening (reason, scope, attendees, hash check)
    oe_estimate_archive_event       - append-only audit trail: who read, opened, closed, verified
    oe_estimate_archive_derivation  - a change position priced from the seal, methods side by side

Cross-module references (project, contract, bill, document, signing session,
variation, change order) are plain GUIDs: deleting a bill must never take its
seal with it, and that is the whole point of a seal.

Immutability (rule S2): the content columns of a seal are guarded twice. The
ORM refuses a flush that changes them or deletes the row, and on PostgreSQL a
trigger rejects UPDATE of those columns and every DELETE. The trigger is made
with the table and again at module startup, so create_all installs carry it. Status
moves (sealed -> opening requested -> open -> closed) are visibility events,
not content, and stay writable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

#: Columns of a seal that are its content. Nothing may change them after insert.
SEAL_CONTENT_COLUMNS: tuple[str, ...] = (
    "project_id",
    "contract_id",
    "source_boq_id",
    "label",
    "schema_version",
    "payload",
    "content_hash",
    "sealed_at",
    "sealed_by",
    "tsa_token",
    "tsa_authority",
    "award_total",
    "currency",
    "basis_kind",
    "deposit_mode",
    "supersedes_id",
    "supersede_reason",
)


class SealImmutableError(RuntimeError):
    """A flush tried to change the content of a sealed estimate."""


class EstimateSeal(Base):
    """A sealed, fingerprinted copy of the estimate behind the contract rates."""

    __tablename__ = "oe_estimate_archive_seal"
    __table_args__ = (Index("ix_oe_estimate_archive_seal_project_status", "project_id", "status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    source_boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="oe.estimate_seal/1")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    #: Base64 DER TimeStampResp from an RFC 3161 authority, when one is configured.
    tsa_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    tsa_authority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    award_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    #: ``tender``, ``award`` or ``negotiated``.
    basis_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="award")
    #: ``sealed``, ``opening_requested``, ``open``, ``closed`` or ``superseded``.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="sealed", index=True)
    #: ``platform`` (kept here) or ``external`` (handed over on paper or media).
    deposit_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="platform")
    retention_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    supersede_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Market profile the seal was made under (``de``, ``uk``, ``us``, ``fidic``, ``neutral``).
    profile: Mapped[str] = mapped_column(String(20), nullable=False, default="neutral")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"<EstimateSeal {self.label} {self.content_hash[:8]}>"


@event.listens_for(EstimateSeal, "before_update")
def _refuse_content_change(_mapper: object, _connection: object, target: EstimateSeal) -> None:
    state = inspect(target)
    changed = [name for name in SEAL_CONTENT_COLUMNS if state.attrs[name].history.has_changes()]
    if changed:
        raise SealImmutableError(f"sealed estimate content is immutable: {', '.join(changed)}")


@event.listens_for(EstimateSeal, "before_delete")
def _refuse_delete(_mapper: object, _connection: object, target: EstimateSeal) -> None:
    raise SealImmutableError(f"a sealed estimate cannot be deleted: {target.id}")


def _guard_statements() -> list[str]:
    table = EstimateSeal.__tablename__
    changed = " OR ".join(f'NEW."{c}" IS DISTINCT FROM OLD."{c}"' for c in SEAL_CONTENT_COLUMNS if c != "payload")
    return [
        f"""
        CREATE OR REPLACE FUNCTION oe_estimate_archive_seal_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ARC_MUTATION_REFUSED: a sealed estimate cannot be deleted';
            END IF;
            IF {changed} OR NEW.payload::text IS DISTINCT FROM OLD.payload::text THEN
                RAISE EXCEPTION 'ARC_MUTATION_REFUSED: sealed estimate content is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        f'DROP TRIGGER IF EXISTS oe_estimate_archive_seal_guard ON "{table}"',
        f'CREATE TRIGGER oe_estimate_archive_seal_guard BEFORE UPDATE OR DELETE ON "{table}" '
        "FOR EACH ROW EXECUTE FUNCTION oe_estimate_archive_seal_guard()",
    ]


def install_seal_guard(connection: Any) -> None:
    """Create the PostgreSQL immutability trigger; idempotent, a no-op on other dialects."""
    if connection.dialect.name != "postgresql":
        return
    for sql in _guard_statements():
        connection.exec_driver_sql(sql)


def _guard_after_create(_table: object, connection: Any, **_kw: object) -> None:
    install_seal_guard(connection)


# create_all builds fresh installs and is then stamped, so the migration's trigger never runs there.
event.listen(EstimateSeal.__table__, "after_create", _guard_after_create)


class EstimateSealAttachment(Base):
    """A file sealed with the estimate, by document id and its hash at seal time."""

    __tablename__ = "oe_estimate_archive_attachment"

    seal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_estimate_archive_seal.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="document")
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class EstimateSealReceipt(Base):
    """The counterparty's acknowledgement of a seal's fingerprint."""

    __tablename__ = "oe_estimate_archive_receipt"

    seal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_estimate_archive_seal.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: ``signing`` (a signing session over the hash) or ``external`` (paper or media receipt).
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="signing")
    signing_session_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    external_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    acknowledged_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: ``requested``, ``signed`` or ``external``.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SealOpening(Base):
    """One recorded opening of a seal. Rows are never deleted."""

    __tablename__ = "oe_estimate_archive_opening"

    seal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_estimate_archive_seal.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    #: ``variation``, ``claim``, ``dispute``, ``final_account``, ``audit`` or ``other``.
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    reference_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    reference_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    #: ``full`` or ``positions``.
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="full")
    scope_ordinals: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: ``[{user_id?, name, organisation, role, side: internal|counterparty, present}]``
    attendees: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    one_party_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: ``requested``, ``open``, ``closed`` or ``halted`` (fingerprint mismatch).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ``ok`` or ``mismatch``; NULL until the opening starts.
    hash_check: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hash_seen: Mapped[str | None] = mapped_column(String(64), nullable=True)
    minutes_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    positions_viewed: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class SealEvent(Base):
    """Append-only audit row. Names the actor in full and is never pruned.

    The platform audit log nulls IP and user agent after 180 days; the
    identity of the people at an opening has to outlive that, so it is kept
    here in its own words.
    """

    __tablename__ = "oe_estimate_archive_event"
    __table_args__ = (Index("ix_oe_estimate_archive_event_seal_created", "seal_id", "created_at"),)

    seal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_estimate_archive_seal.id", ondelete="RESTRICT"), nullable=False
    )
    opening_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    #: sealed, receipt_requested, receipt_signed, receipt_external, read, position_viewed,
    #: verified, opening_requested, opening_started, hash_check, opening_closed, minutes,
    #: superseded, derivation_recorded, export.
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    actor_organisation: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class SealDerivation(Base):
    """A change position priced from the seal; every method shown, one recorded by a person."""

    __tablename__ = "oe_estimate_archive_derivation"

    seal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_estimate_archive_seal.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position_ordinal: Mapped[str] = mapped_column(String(50), nullable=False)
    variation_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    change_order_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    reference_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    #: The derivation inputs (changes, additions, removals, today's costs).
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: The engine result at the time of recording.
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: ``original_basis``, ``cost_plus_markup``, ``agreed``, ``daywork`` or NULL (not chosen yet).
    basis_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    chosen_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    #: Bill position written into the variation's own bill, when one was.
    variation_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
