# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""sealed original estimate: seals, files, receipts, openings, audit events, derivations

Six new tables and three nullable columns on ``oe_variations_boq_trace``
(``sealed_seal_id``, ``sealed_position_ordinal``, ``basis_method``). On a
running install the boot-time schema heal adds the columns and create_all the
tables, so a stamp is enough for those.

The PostgreSQL trigger that refuses UPDATE of a seal's content columns and any
DELETE of a seal is only installed by this revision. This migration MUST be RUN
(``alembic upgrade``), not merely stamped, for the database itself to enforce
immutability; without it the ORM guard and the API (409 on every change) still
refuse.

Revision ID: vea01_estimate_archive
Revises: vdx01_booking_export
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vea01_estimate_archive"
down_revision: str | Sequence[str] | None = "vdx01_booking_export"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEAL = "oe_estimate_archive_seal"
_TRACE = "oe_variations_boq_trace"
_CONTENT = (
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


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _seal_fk() -> sa.Column:
    return sa.Column("seal_id", sa.String(36), sa.ForeignKey(f"{_SEAL}.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if _SEAL not in tables:
        op.create_table(
            _SEAL,
            *_base(),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("contract_id", sa.String(36), nullable=True),
            sa.Column("source_boq_id", sa.String(36), nullable=True),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("schema_version", sa.String(40), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sealed_by", sa.String(36), nullable=True),
            sa.Column("tsa_token", sa.Text(), nullable=True),
            sa.Column("tsa_authority", sa.String(255), nullable=True),
            sa.Column("award_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("basis_kind", sa.String(20), nullable=False, server_default="award"),
            sa.Column("status", sa.String(20), nullable=False, server_default="sealed"),
            sa.Column("deposit_mode", sa.String(20), nullable=False, server_default="platform"),
            sa.Column("retention_until", sa.String(40), nullable=True),
            sa.Column("supersedes_id", sa.String(36), nullable=True),
            sa.Column("supersede_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("profile", sa.String(20), nullable=False, server_default="neutral"),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_verified_ok", sa.Boolean(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        for col in ("project_id", "contract_id", "source_boq_id", "content_hash", "status", "supersedes_id"):
            op.create_index(f"ix_{_SEAL}_{col}", _SEAL, [col])
        op.create_index(f"ix_{_SEAL}_project_status", _SEAL, ["project_id", "status"])

    t = "oe_estimate_archive_attachment"
    if t not in tables:
        op.create_table(
            t,
            *_base(),
            _seal_fk(),
            sa.Column("document_id", sa.String(36), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(40), nullable=False, server_default="document"),
            sa.Column("file_hash", sa.String(64), nullable=False),
        )
        op.create_index(f"ix_{t}_seal_id", t, ["seal_id"])

    t = "oe_estimate_archive_receipt"
    if t not in tables:
        op.create_table(
            t,
            *_base(),
            _seal_fk(),
            sa.Column("kind", sa.String(20), nullable=False, server_default="signing"),
            sa.Column("signing_session_id", sa.String(36), nullable=True),
            sa.Column("external_reference", sa.String(255), nullable=False, server_default=""),
            sa.Column("receipt_document_id", sa.String(36), nullable=True),
            sa.Column("acknowledged_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="requested"),
            sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index(f"ix_{t}_seal_id", t, ["seal_id"])

    t = "oe_estimate_archive_opening"
    if t not in tables:
        op.create_table(
            t,
            *_base(),
            _seal_fk(),
            sa.Column("requested_by", sa.String(36), nullable=True),
            sa.Column("reason", sa.String(20), nullable=False),
            sa.Column("reference_type", sa.String(40), nullable=False, server_default=""),
            sa.Column("reference_id", sa.String(36), nullable=True),
            sa.Column("reference_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("scope", sa.String(20), nullable=False, server_default="full"),
            sa.Column("scope_ordinals", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("attendees", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("one_party_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="requested"),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hash_check", sa.String(20), nullable=True),
            sa.Column("hash_seen", sa.String(64), nullable=True),
            sa.Column("minutes_document_id", sa.String(36), nullable=True),
            sa.Column("positions_viewed", sa.JSON(), nullable=False, server_default="[]"),
        )
        for col in ("seal_id", "status"):
            op.create_index(f"ix_{t}_{col}", t, [col])

    t = "oe_estimate_archive_event"
    if t not in tables:
        op.create_table(
            t,
            *_base(),
            _seal_fk(),
            sa.Column("opening_id", sa.String(36), nullable=True),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("actor_id", sa.String(36), nullable=True),
            sa.Column("actor_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("actor_organisation", sa.String(255), nullable=False, server_default=""),
            sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        )
        for col in ("event_type", "actor_id"):
            op.create_index(f"ix_{t}_{col}", t, [col])
        op.create_index(f"ix_{t}_seal_created", t, ["seal_id", "created_at"])

    t = "oe_estimate_archive_derivation"
    if t not in tables:
        op.create_table(
            t,
            *_base(),
            _seal_fk(),
            sa.Column("position_ordinal", sa.String(50), nullable=False),
            sa.Column("variation_request_id", sa.String(36), nullable=True),
            sa.Column("change_order_item_id", sa.String(36), nullable=True),
            sa.Column("reference_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("basis_method", sa.String(30), nullable=True),
            sa.Column("chosen_rate", sa.Numeric(18, 2), nullable=True),
            sa.Column("variation_position_id", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        for col in ("seal_id", "variation_request_id", "change_order_item_id"):
            op.create_index(f"ix_{t}_{col}", t, [col])

    if _TRACE in tables:
        have = {c["name"] for c in sa.inspect(bind).get_columns(_TRACE)}
        if "sealed_seal_id" not in have:
            op.add_column(_TRACE, sa.Column("sealed_seal_id", sa.String(36), nullable=True))
            op.create_index(f"ix_{_TRACE}_sealed_seal_id", _TRACE, ["sealed_seal_id"])
        if "sealed_position_ordinal" not in have:
            op.add_column(_TRACE, sa.Column("sealed_position_ordinal", sa.String(50), nullable=True))
        if "basis_method" not in have:
            op.add_column(_TRACE, sa.Column("basis_method", sa.String(30), nullable=True))

    if bind.dialect.name == "postgresql":
        changed = " OR ".join(f'NEW."{c}" IS DISTINCT FROM OLD."{c}"' for c in _CONTENT if c != "payload")
        op.execute(
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
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(f'DROP TRIGGER IF EXISTS oe_estimate_archive_seal_guard ON "{_SEAL}"')
        op.execute(
            f'CREATE TRIGGER oe_estimate_archive_seal_guard BEFORE UPDATE OR DELETE ON "{_SEAL}" '
            "FOR EACH ROW EXECUTE FUNCTION oe_estimate_archive_seal_guard()"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f'DROP TRIGGER IF EXISTS oe_estimate_archive_seal_guard ON "{_SEAL}"')
        op.execute("DROP FUNCTION IF EXISTS oe_estimate_archive_seal_guard()")
    have = {c["name"] for c in sa.inspect(bind).get_columns(_TRACE)}
    if "sealed_seal_id" in have:
        op.drop_index(f"ix_{_TRACE}_sealed_seal_id", table_name=_TRACE)
    for col in ("basis_method", "sealed_position_ordinal", "sealed_seal_id"):
        if col in have:
            op.drop_column(_TRACE, col)
    for t in ("derivation", "event", "opening", "receipt", "attachment"):
        op.drop_table(f"oe_estimate_archive_{t}")
    op.drop_table(_SEAL)
