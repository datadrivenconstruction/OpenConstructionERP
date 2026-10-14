"""A purchase order's VAT rate, so its tax follows the net (#515).

One nullable column, added only when missing, so a database the boot-time
column healer already touched upgrades cleanly. NULL keeps the tax as typed.

Revision ID: v69_po_tax_rate
Revises: v68_projects_works
"""

import sqlalchemy as sa
from alembic import op

revision = "v69_po_tax_rate"
down_revision = "v68_projects_works"
branch_labels = None
depends_on = None

_TABLE = "oe_procurement_po"
_COLUMN = "tax_rate"


def _existing(inspector) -> set[str] | None:
    if not inspector.has_table(_TABLE):
        return None
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    present = _existing(sa.inspect(op.get_bind()))
    if present is not None and _COLUMN not in present:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(20), nullable=True))


def downgrade() -> None:
    present = _existing(sa.inspect(op.get_bind()))
    if present is not None and _COLUMN in present:
        op.drop_column(_TABLE, _COLUMN)
