"""Batch or lot and serial numbers on procurement goods receipt lines.

Procurement is the one purchasing flow; the supplier catalogue receipt line
carried batch/lot and serial numbers, so the canonical line now carries them
too. Both columns are nullable and added only when missing, so a database the
boot-time column healer already touched upgrades cleanly.

Revision ID: v59_gr_item_batch_serial
Revises: v58_owner_list_indexes
"""

import sqlalchemy as sa
from alembic import op

revision = "v59_gr_item_batch_serial"
down_revision = "v58_owner_list_indexes"
branch_labels = None
depends_on = None

_TABLE = "oe_procurement_gr_item"
_COLUMNS = (
    ("batch_lot", sa.String(100)),
    ("serial_numbers", sa.JSON()),
)


def _existing(bind) -> set[str] | None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return None
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    existing = _existing(op.get_bind())
    if existing is None:
        return
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    existing = _existing(op.get_bind())
    if existing is None:
        return
    for name, _type in reversed(_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
