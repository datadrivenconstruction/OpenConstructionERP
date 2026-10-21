# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontractors - link a subcontractor contact person to the contacts directory.

One additive nullable column, no data rewrite:

* ``oe_subcontractors_subcontractor_contact.contact_id``: the canonical ``oe_contacts_contact`` row
  for this person (FK, ``ON DELETE SET NULL``), indexed. Existing rows stay unlinked until the
  backfill script (``scripts/backfill_subcontractor_contact_links.py``) is run.

The step is inspector-guarded, so a database whose table ``create_all`` already built reaches this
revision and does nothing.

Revision ID: v199_subcontractor_contact_link
Revises: v198_requisition_over_allocation_reason
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v199_subcontractor_contact_link"
down_revision: str | Sequence[str] | None = "v198_requisition_over_allocation_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_subcontractors_subcontractor_contact"
_COLUMN = "contact_id"
_INDEX = "ix_oe_subcontractors_subcontractor_contact_contact_id"
_FK = "fk_oe_subcontractors_subcontractor_contact_contact_id"
_TARGET = "oe_contacts_contact"


def upgrade() -> None:
    """Add the column, its index and the foreign key when missing."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if _TABLE not in tables:
        return
    if _COLUMN not in {c["name"] for c in insp.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, GUID(), nullable=True))
        if _TARGET in tables and bind.dialect.name != "sqlite":
            op.create_foreign_key(_FK, _TABLE, _TARGET, [_COLUMN], ["id"], ondelete="SET NULL")
    if _INDEX not in {i["name"] for i in sa.inspect(bind).get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    """Drop the index, foreign key and column when present."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in set(insp.get_table_names()):
        return
    if _INDEX in {i["name"] for i in insp.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}:
        if bind.dialect.name != "sqlite" and _FK in {f["name"] for f in insp.get_foreign_keys(_TABLE)}:
            op.drop_constraint(_FK, _TABLE, type_="foreignkey")
        op.drop_column(_TABLE, _COLUMN)
