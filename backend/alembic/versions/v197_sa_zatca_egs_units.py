# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""sa_zatca - the EGS units of a Saudi registration and the chain each keeps.

Two new tables, no column on an existing one and no data rewrite:

* ``oe_einvoice_zatca_egs_unit``: one e-invoice generation solution unit, its onboarding state, its
  certificates (secrets encrypted) and the head of its invoice chain (last counter, last hash).
* ``oe_einvoice_zatca_chain_entry``: one row per counter a unit allocated, unique on (unit, counter).

Pip and desktop installs never run this revision: ``create_all`` builds the tables from the models on
boot. Every step is inspector-guarded, so a database whose tables ``create_all`` already built reaches
this revision without error.

Revision ID: v197_sa_zatca_egs_units
Revises: v195_eg_tax_payee_exemption
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v197_sa_zatca_egs_units"
down_revision: str | Sequence[str] | None = "v195_eg_tax_payee_exemption"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIT = "oe_einvoice_zatca_egs_unit"
_ENTRY = "oe_einvoice_zatca_chain_entry"


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _text(name: str) -> sa.Column:
    return sa.Column(name, sa.Text(), nullable=False, server_default="")


def _ensure_indexes(
    bind: sa.engine.Connection, table: str, wanted: tuple[tuple[str, list[str]], ...], *, unique: bool = False
) -> None:
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}
    for name, cols in wanted:
        if name not in existing:
            op.create_index(name, table, cols, unique=unique)


def upgrade() -> None:
    """Create the two tables."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _UNIT not in tables:
        op.create_table(
            _UNIT,
            *_base_columns(),
            sa.Column(
                "profile_id",
                GUID(),
                sa.ForeignKey(
                    "oe_einvoice_clearance_profile.id",
                    ondelete="CASCADE",
                    name="fk_oe_einvoice_zatca_egs_unit_profile_id",
                ),
                nullable=False,
            ),
            sa.Column("unit_key", sa.String(120), nullable=False),
            sa.Column("csr_fields", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("state", sa.String(24), nullable=False, server_default="new"),
            sa.Column("environment", sa.String(32), nullable=False, server_default=""),
            _text("private_key_encrypted"),
            sa.Column("signer_kind", sa.String(32), nullable=False, server_default=""),
            sa.Column("signer_config", sa.JSON(), nullable=False, server_default="{}"),
            _text("csr_pem"),
            sa.Column("compliance_request_id", sa.String(64), nullable=False, server_default=""),
            _text("compliance_token"),
            _text("compliance_secret_encrypted"),
            sa.Column("production_request_id", sa.String(64), nullable=False, server_default=""),
            _text("production_token"),
            _text("production_secret_encrypted"),
            sa.Column("certificate_not_after", sa.DateTime(timezone=True), nullable=True),
            sa.Column("compliance_results", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("last_icv", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_hash", sa.String(128), nullable=False, server_default=""),
            _text("last_error"),
            sa.PrimaryKeyConstraint("id", name="pk_oe_einvoice_zatca_egs_unit"),
            sa.UniqueConstraint("profile_id", "unit_key", name="uq_einvoice_zatca_egs_unit_profile_key"),
        )
    _ensure_indexes(bind, _UNIT, (("ix_einvoice_zatca_egs_unit_profile", ["profile_id", "state"]),))

    if _ENTRY not in tables:
        op.create_table(
            _ENTRY,
            *_base_columns(),
            sa.Column(
                "unit_id",
                GUID(),
                sa.ForeignKey(
                    f"{_UNIT}.id",
                    ondelete="CASCADE",
                    name="fk_oe_einvoice_zatca_chain_entry_unit_id",
                ),
                nullable=False,
            ),
            sa.Column("icv", sa.Integer(), nullable=False),
            sa.Column("invoice_uuid", sa.String(36), nullable=False),
            sa.Column("invoice_number", sa.String(64), nullable=False, server_default=""),
            sa.Column("invoice_id", GUID(), nullable=True),
            sa.Column("previous_hash", sa.String(128), nullable=False),
            sa.Column("invoice_hash", sa.String(128), nullable=False),
            sa.Column("type_code", sa.String(3), nullable=False, server_default=""),
            sa.Column("subtype", sa.String(7), nullable=False, server_default=""),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_einvoice_zatca_chain_entry"),
            sa.UniqueConstraint("unit_id", "icv", name="uq_einvoice_zatca_chain_entry_unit_icv"),
        )
    _ensure_indexes(bind, _ENTRY, (("ix_einvoice_zatca_chain_entry_uuid", ["invoice_uuid"]),), unique=True)


def downgrade() -> None:
    """Drop the two tables."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in (_ENTRY, _UNIT):
        if table in tables:
            op.drop_table(table)
