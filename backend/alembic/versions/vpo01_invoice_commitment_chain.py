# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Invoice names its subcontract agreement, a scheduled payment date and who approved it

* ``oe_finance_invoice.subcontract_agreement_id``: the subcontract a payable
  bills against, beside ``purchase_order_id``. Indexed.
* ``scheduled_payment_date``: when the payment is planned, distinct from the
  contractual ``due_date``.
* ``submitted_by`` / ``submitted_at`` / ``approved_by`` / ``approved_at``: who
  sent the invoice for approval and who approved it.

All nullable and additive, so the boot heal and ``alembic upgrade`` agree.

Revision ID: vpo01_invoice_commitment_chain
Revises: vsub01_submittal_distribution
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vpo01_invoice_commitment_chain"
down_revision: str | Sequence[str] | None = "vsub01_submittal_distribution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_finance_invoice"
_GUID = sa.String(36)
_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("subcontract_agreement_id", _GUID),
    ("scheduled_payment_date", sa.String(40)),
    ("submitted_by", _GUID),
    ("submitted_at", sa.String(40)),
    ("approved_by", _GUID),
    ("approved_at", sa.String(40)),
)
_INDEX = "ix_invoice_subcontract_agreement"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    missing = [(name, kind) for name, kind in _COLUMNS if name not in present]
    if missing:
        with op.batch_alter_table(_TABLE) as batch:
            for name, kind in missing:
                batch.add_column(sa.Column(name, kind, nullable=True))
    if _INDEX not in {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["subcontract_agreement_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _INDEX in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    dropping = [name for name, _ in _COLUMNS if name in present]
    if dropping:
        with op.batch_alter_table(_TABLE) as batch:
            for name in dropping:
                batch.drop_column(name)
