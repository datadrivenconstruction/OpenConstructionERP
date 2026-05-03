"""v2.6.49 — compound (project_id, type) indexes for hot list filters.

Three modules previously filtered list endpoints by ``type``-style columns
without an index, falling back to full table scans inside the project's
rows. At 1k+ rows per project the cost is visible:

* ``oe_meetings_meeting``         → ``(project_id, meeting_type)``
* ``oe_inspections_inspection``    → ``(project_id, inspection_type)``
* ``oe_fieldreports_report``       → ``(project_id, report_type)``

Inspector-guarded so re-running on an already-migrated DB is a no-op.

Revision ID: v2b1_compound_type_indexes
Revises: v2b0_preset_sync_columns
Create Date: 2026-05-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2b1_compound_type_indexes"
down_revision: Union[str, Sequence[str], None] = "v2b0_preset_sync_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES: list[tuple[str, str, list[str]]] = [
    (
        "ix_oe_meetings_meeting_project_type",
        "oe_meetings_meeting",
        ["project_id", "meeting_type"],
    ),
    (
        "ix_oe_inspections_inspection_project_type",
        "oe_inspections_inspection",
        ["project_id", "inspection_type"],
    ),
    (
        "ix_oe_fieldreports_report_project_type",
        "oe_fieldreports_report",
        ["project_id", "report_type"],
    ),
]


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector, table: str, name: str
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table, cols in _INDEXES:
        if not _has_table(inspector, table):
            continue
        if _has_index(inspector, table, name):
            continue
        op.create_index(name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table, _cols in _INDEXES:
        if _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)
