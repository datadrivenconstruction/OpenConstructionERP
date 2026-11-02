# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""einvoice_clearance: transport mode, document kind, hash chain and period.

Adds ``mode`` (export | sandbox | live; empty for registrations made before modes) to
``oe_einvoice_clearance_profile`` and ``document_kind``, ``previous_hash`` and
``period`` to ``oe_einvoice_clearance_document``. All NOT NULL with server
defaults, so existing rows read as export-mode standard documents. Additive and
idempotent (inspector-guarded); the boot heal adds the same columns from the ORM.

Revision ID: v3345_einvoice_lifecycle
Revises: v3344_user_secondary_calendar
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3345_einvoice_lifecycle"
down_revision: str | Sequence[str] | None = "v3344_user_secondary_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE = "oe_einvoice_clearance_profile"
_DOCUMENT = "oe_einvoice_clearance_document"

# (name, length, server default)
_COLUMNS: dict[str, list[tuple[str, int, str]]] = {
    _PROFILE: [("mode", 8, "")],
    _DOCUMENT: [("document_kind", 16, "standard"), ("previous_hash", 128, ""), ("period", 7, "")],
}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        present = {c["name"] for c in insp.get_columns(table)}
        for name, length, default in columns:
            if name not in present:
                op.add_column(table, sa.Column(name, sa.String(length), nullable=False, server_default=default))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        present = {c["name"] for c in insp.get_columns(table)}
        for name, _length, _default in columns:
            if name in present:
                op.drop_column(table, name)
