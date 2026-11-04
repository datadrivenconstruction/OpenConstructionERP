# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Add due date and verification columns to NCR.

``due_date`` lets the overdue rule judge an open NCR; ``verified_by`` and
``verified_at`` record who verified the fix when it was closed. All nullable.
Inspector-guarded so a database the runtime already built from the models is
a no-op.

Revision ID: vncr01_ncr_due_verified
Revises: vfsl01_field_sync_ledger_project
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "vncr01_ncr_due_verified"
down_revision = "vfsl01_field_sync_ledger_project"
branch_labels = None
depends_on = None

_TABLE = "oe_ncr_ncr"
_COLUMNS = (
    ("due_date", sa.Date()),
    ("verified_by", sa.String(length=36)),
    ("verified_at", sa.DateTime(timezone=True)),
)


def _existing() -> set[str] | None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return None
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    have = _existing()
    if have is None:
        return
    for name, type_ in _COLUMNS:
        if name not in have:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    have = _existing()
    if have is None:
        return
    for name, _type in reversed(_COLUMNS):
        if name in have:
            op.drop_column(_TABLE, name)
