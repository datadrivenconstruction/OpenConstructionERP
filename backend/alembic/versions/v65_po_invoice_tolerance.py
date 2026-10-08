"""How far a supplier invoice may run past its purchase order before warning.

Two nullable columns, added only when missing, so a database the boot-time
column healer already touched upgrades cleanly. NULL keeps the one-cent rounding band.

Revision ID: v65_po_invoice_tolerance
Revises: v64_po_supplier_acknowledgement
"""

import sqlalchemy as sa
from alembic import op

revision = "v65_po_invoice_tolerance"
down_revision = "v64_po_supplier_acknowledgement"
branch_labels = None
depends_on = None

_TABLE = "oe_procurement_po"
_COLUMNS = (
    ("invoice_tolerance_pct", 20),
    ("invoice_tolerance_abs", 50),
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
