# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests: per-request checklist overrides.

One additive column, inspector-guarded like v0002, so a database that
already has it - a fresh install built from the models, or one healed at
boot - passes straight through.

    oe_work_requests_request.checklist_overrides   the per-request diff

The column holds the DIFFERENCE from the request type's checklist, never
a copy of it: ``{"added": [...], "hidden": [...], "edits": {...},
"order": [...]}``. Empty (``{}``) is "use the type's list", which is
exactly what every existing row means.

Revision ID: oe_work_requests_v0003_checklist_overrides
Revises: oe_work_requests_v0002_expansion
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "oe_work_requests_v0003_checklist_overrides"
down_revision: str | Sequence[str] | None = "oe_work_requests_v0002_expansion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST = "oe_work_requests_request"
_COLUMN = "checklist_overrides"


def _columns(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    have = _columns(inspector, _REQUEST)
    if have and _COLUMN not in have:
        op.add_column(_REQUEST, sa.Column(_COLUMN, sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _COLUMN in _columns(inspector, _REQUEST):
        op.drop_column(_REQUEST, _COLUMN)
