# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""payment_release - payment terms, invoice releases and retention postings.

Three new tables, no column on an existing one and no data rewrite:

* ``oe_payment_release_terms``: a contract's payment terms (invoice mode, retention basis, warranty
  retention, early payment discount, rounding, due days), one row per contract. A contract without a row
  is read with the defaults, every optional feature off, so nothing needs a backfill.
* ``oe_payment_release_invoice``: a supplier invoice's kind, contract and agreed deductions, and the
  release a person confirmed (frozen figures and the full step list).
* ``oe_payment_release_posting``: held retention paid back on a date, after its event.

Pip and desktop installs never run this revision: ``create_all`` builds the tables from the models on
boot. Every step is inspector-guarded, so a database whose tables ``create_all`` already built reaches
this revision without error.

Revision ID: v94_payment_release
Revises: v93_costmodel_cost_inheritance
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.db_types import MoneyType
from app.database import GUID

revision: str = "v94_payment_release"
down_revision: str | Sequence[str] | None = "v93_costmodel_cost_inheritance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TERMS = "oe_payment_release_terms"
_INVOICE = "oe_payment_release_invoice"
_POSTING = "oe_payment_release_posting"


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _project_fk(name: str) -> sa.Column:
    return sa.Column(
        "project_id",
        GUID(),
        sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE", name=name),
        nullable=False,
    )


def _contract_fk(name: str) -> sa.Column:
    return sa.Column(
        "contract_id",
        GUID(),
        sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE", name=name),
        nullable=False,
    )


def _indexes(bind: sa.engine.Connection, table: str) -> set[str]:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def _ensure_indexes(bind: sa.engine.Connection, table: str, wanted: tuple[tuple[str, list[str]], ...]) -> None:
    existing = _indexes(bind, table)
    for name, cols in wanted:
        if name not in existing:
            op.create_index(name, table, cols)


def upgrade() -> None:
    """Create the three tables."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _TERMS not in tables:
        op.create_table(
            _TERMS,
            *_base_columns(),
            _contract_fk("fk_oe_payment_release_terms_contract_id_oe_contracts_contract"),
            _project_fk("fk_oe_payment_release_terms_project_id_oe_projects_project"),
            sa.Column("invoice_mode", sa.String(20), nullable=False, server_default="incremental"),
            sa.Column("retention_basis", sa.String(10), nullable=False, server_default="net"),
            sa.Column("warranty_enabled", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("warranty_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("warranty_release_event", sa.String(40), nullable=False, server_default="defects_period_end"),
            sa.Column("warranty_period_months", sa.Integer(), nullable=True),
            sa.Column("discount_enabled", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("discount_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("discount_applies_to", sa.String(10), nullable=False, server_default="both"),
            sa.Column("rounding_enabled", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("rounding_step", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("interim_due_days", sa.Integer(), nullable=True),
            sa.Column("final_due_days", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.PrimaryKeyConstraint("id", name="pk_oe_payment_release_terms"),
            sa.UniqueConstraint("contract_id", name="uq_payment_release_terms_contract"),
        )
    _ensure_indexes(bind, _TERMS, (("ix_oe_payment_release_terms_project_id", ["project_id"]),))

    if _INVOICE not in tables:
        op.create_table(
            _INVOICE,
            *_base_columns(),
            sa.Column("invoice_id", GUID(), nullable=False),
            _project_fk("fk_oe_payment_release_invoice_project_id_oe_projects_project"),
            sa.Column("contract_id", GUID(), nullable=True),
            sa.Column("kind", sa.String(20), nullable=False, server_default="interim"),
            sa.Column("net_deduction", MoneyType(), nullable=False, server_default="0"),
            sa.Column("net_deduction_note", sa.String(500), nullable=True),
            sa.Column("gross_deduction", MoneyType(), nullable=False, server_default="0"),
            sa.Column("gross_deduction_note", sa.String(500), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("released_by", sa.String(36), nullable=True),
            sa.Column("release_amount", MoneyType(), nullable=True),
            sa.Column("payable_amount", MoneyType(), nullable=True),
            sa.Column("retention_amount", MoneyType(), nullable=True),
            sa.Column("rounding_amount", MoneyType(), nullable=True),
            sa.Column("discount_amount", MoneyType(), nullable=True),
            sa.Column("snapshot", sa.JSON(), nullable=False, server_default="{}"),
            sa.PrimaryKeyConstraint("id", name="pk_oe_payment_release_invoice"),
            sa.UniqueConstraint("invoice_id", name="uq_payment_release_invoice_invoice"),
        )
    _ensure_indexes(
        bind,
        _INVOICE,
        (
            ("ix_oe_payment_release_invoice_project_id", ["project_id"]),
            ("ix_oe_payment_release_invoice_contract_id", ["contract_id"]),
            ("ix_oe_payment_release_invoice_status", ["status"]),
        ),
    )

    if _POSTING not in tables:
        op.create_table(
            _POSTING,
            *_base_columns(),
            _project_fk("fk_oe_payment_release_posting_project_id_oe_projects_project"),
            _contract_fk("fk_oe_payment_release_posting_contract_id_oe_contracts_contract"),
            sa.Column("retention_kind", sa.String(20), nullable=False),
            sa.Column("event", sa.String(40), nullable=False),
            sa.Column("event_on", sa.Date(), nullable=True),
            sa.Column("amount", MoneyType(), nullable=False),
            sa.Column("posted_on", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="posted"),
            sa.Column("document_ref", sa.String(255), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("voided_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.PrimaryKeyConstraint("id", name="pk_oe_payment_release_posting"),
        )
    _ensure_indexes(
        bind,
        _POSTING,
        (
            ("ix_oe_payment_release_posting_project_id", ["project_id"]),
            ("ix_oe_payment_release_posting_contract_id", ["contract_id"]),
        ),
    )


def downgrade() -> None:
    """Drop the three tables."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in (_POSTING, _INVOICE, _TERMS):
        if table in tables:
            op.drop_table(table)
