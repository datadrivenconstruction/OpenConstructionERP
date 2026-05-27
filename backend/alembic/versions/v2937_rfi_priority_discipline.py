"""v2.9.37 — RFI priority + discipline columns.

Adds two nullable columns to ``oe_rfi_rfi`` so the RFI module can record
business-level metadata that drives the row colour-dot, the discipline
chip, and the filter dropdown introduced alongside this migration:

* ``priority``    — ``low | normal | high | critical`` (validated by the
                    Pydantic schema; free-form on the DB side).
* ``discipline``  — ``architectural | structural | mep | electrical |
                    plumbing | civil | landscape`` (free-form server-side
                    so future disciplines can land without a migration —
                    the frontend picker constrains the values).

Both columns are nullable so pre-existing rows survive the upgrade
untouched. Downgrade drops the columns.

Revision ID: v2937_rfi_priority_discipline
Revises: v2936_match_search_log_feedback
Create Date: 2026-05-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2937_rfi_priority_discipline"
down_revision: Union[str, Sequence[str], None] = "v2936_match_search_log_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_rfi_rfi"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(col["name"] == name for col in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if not _has_column(inspector, _TABLE, "priority"):
        op.add_column(
            _TABLE,
            sa.Column("priority", sa.String(length=20), nullable=True),
        )
    if not _has_column(inspector, _TABLE, "discipline"):
        op.add_column(
            _TABLE,
            sa.Column("discipline", sa.String(length=50), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if _has_column(inspector, _TABLE, "discipline"):
        op.drop_column(_TABLE, "discipline")
    if _has_column(inspector, _TABLE, "priority"):
        op.drop_column(_TABLE, "priority")
