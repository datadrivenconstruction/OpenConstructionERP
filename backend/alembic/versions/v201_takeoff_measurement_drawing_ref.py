# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""takeoff - the drawing sheet and revision a measurement was taken from.

Additive nullable columns on ``oe_takeoff_measurement``, no data rewrite:

* ``drawing_document_id``: the Project Files document (``oe_documents_document``) of the sheet.
* ``drawing_sheet_id``: the ``oe_documents_sheet`` row of the page, when the register has one.
* ``drawing_number``, ``drawing_title``, ``drawing_revision``: the title block as it read when the
  quantity was taken, so a later revision can be told apart from the one that was priced.

Rows taken before this revision read NULL, which means "not recorded", not "no drawing".
The steps are inspector-guarded, so a database whose table ``create_all`` already built reaches this
revision and does nothing.

Revision ID: v201_takeoff_measurement_drawing_ref
Revises: v199_subcontractor_contact_link
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v201_takeoff_measurement_drawing_ref"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_takeoff_measurement"
_COLUMNS: tuple[tuple[str, int], ...] = (
    ("drawing_document_id", 36),
    ("drawing_sheet_id", 36),
    ("drawing_number", 100),
    ("drawing_title", 500),
    ("drawing_revision", 50),
)


def upgrade() -> None:
    """Add each column when the table exists and lacks it."""
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    present = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    for name, length in _COLUMNS:
        if name not in present:
            op.add_column(_TABLE, sa.Column(name, sa.String(length), nullable=True))


def downgrade() -> None:
    """Drop the columns when present."""
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    present = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    for name, _length in reversed(_COLUMNS):
        if name in present:
            op.drop_column(_TABLE, name)
