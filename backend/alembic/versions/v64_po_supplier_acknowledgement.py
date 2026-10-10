"""The supplier's confirmation of an issued purchase order.

Four nullable columns, added only when missing, so a database the boot-time
column healer already touched upgrades cleanly. NULL means not confirmed yet.

Revision ID: v64_po_supplier_acknowledgement
Revises: v63_contact_party_kind
"""

import sqlalchemy as sa
from alembic import op

revision = "v64_po_supplier_acknowledgement"
down_revision = "v63_contact_party_kind"
branch_labels = None
depends_on = None

_TABLE = "oe_procurement_po"
_COLUMNS = (
    ("supplier_acknowledged_at", 40),
    ("supplier_acknowledged_by", 36),
    ("supplier_reference", 100),
    ("supplier_confirmed_delivery_date", 40),
)


def _existing(inspector) -> set[str] | None:
    if not inspector.has_table(_TABLE):
        return None
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    present = _existing(sa.inspect(op.get_bind()))
    if present is None:
        return
    for name, length in _COLUMNS:
        if name not in present:
            op.add_column(_TABLE, sa.Column(name, sa.String(length), nullable=True))


def downgrade() -> None:
    present = _existing(sa.inspect(op.get_bind()))
    if present is None:
        return
    for name, _length in reversed(_COLUMNS):
        if name in present:
            op.drop_column(_TABLE, name)
