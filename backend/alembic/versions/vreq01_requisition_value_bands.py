# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Requisition approval by value: per-project value bands

* ``oe_procurement_project_settings.approval_bands``: JSON, the currency and the
  ascending list of bands (start amount and the approvers it adds) a submitted
  requisition is routed on.

Nullable and additive, so the boot heal and ``alembic upgrade`` agree.

Revision ID: vreq01_requisition_value_bands
Revises: vpo01_invoice_commitment_chain
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vreq01_requisition_value_bands"
down_revision: str | Sequence[str] | None = "vpo01_invoice_commitment_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_procurement_project_settings"
_COLUMN = "approval_bands"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
