# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""projects - team-wide project colour.

One additive nullable column, no data rewrite:

* ``oe_projects_project.color``: ``#rrggbb`` chosen for the project. NULL means
  none chosen; the UI derives a stable colour from the id.

The step is inspector-guarded, so a database whose table ``create_all`` already
built reaches this revision and does nothing.

Revision ID: v200_project_color
Revises: vlv01_list_views
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v200_project_color"
down_revision: str | Sequence[str] | None = "vlv01_list_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_projects_project"
_COLUMN = "color"


def _columns() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    """Add the column when missing."""
    cols = _columns()
    if cols and _COLUMN not in cols:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=7), nullable=True))


def downgrade() -> None:
    """Drop the column when present."""
    if _COLUMN in _columns():
        op.drop_column(_TABLE, _COLUMN)
