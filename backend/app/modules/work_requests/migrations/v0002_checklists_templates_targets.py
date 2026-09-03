# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests expansion: checklists, templates, programme links, targets.

Additive columns only - nothing is dropped and nothing is rewritten, so a
database that already has them (a fresh install built from the models, or
one healed at boot) passes straight through. Every column is guarded by
the inspector for exactly that reason: this file must be safe to run on a
half-migrated deployment.

    oe_work_requests_department.target_days           turnaround target
    oe_work_requests_request.request_types            the multi-type list
    oe_work_requests_request.checklist_state          the ticks
    oe_work_requests_request.is_template              kept to copy from
    oe_work_requests_request.schedule_activity_id     programme tie-in
    oe_work_requests_request.boq_position_ids         estimate tie-in
    oe_work_requests_request.accepted_at              the turnaround clock

Revision ID: oe_work_requests_v0002_expansion
Revises: oe_work_requests_v0001_initial
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "oe_work_requests_v0002_expansion"
down_revision: str | Sequence[str] | None = "oe_work_requests_v0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEPARTMENT = "oe_work_requests_department"
_REQUEST = "oe_work_requests_request"

# GUID is VARCHAR(36) on every dialect (see app.database.GUID).
_GUID = sa.String(36)

_COLUMNS: tuple[tuple[str, sa.Column], ...] = (
    (_DEPARTMENT, sa.Column("target_days", sa.Integer(), nullable=True)),
    (_REQUEST, sa.Column("request_types", sa.JSON(), nullable=False, server_default="[]")),
    (_REQUEST, sa.Column("checklist_state", sa.JSON(), nullable=False, server_default="{}")),
    (_REQUEST, sa.Column("is_template", sa.Boolean(), nullable=False, server_default="false")),
    (_REQUEST, sa.Column("schedule_activity_id", _GUID, nullable=True)),
    (_REQUEST, sa.Column("boq_position_ids", sa.JSON(), nullable=False, server_default="[]")),
    (_REQUEST, sa.Column("accepted_at", sa.String(10), nullable=True)),
)


def _columns(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    have: dict[str, set[str]] = {}
    for table, column in _COLUMNS:
        if table not in have:
            have[table] = _columns(inspector, table)
        if not have[table] or column.name in have[table]:
            # The table is absent (v0001 has not run) or the column is
            # already there - either way there is nothing to add here.
            continue
        op.add_column(table, column)
        have[table].add(column.name)

    if _REQUEST in inspector.get_table_names():
        indexes = {i["name"] for i in inspector.get_indexes(_REQUEST)}
        name = f"ix_{_REQUEST}_is_template"
        if name not in indexes and "is_template" in _columns(sa.inspect(op.get_bind()), _REQUEST):
            op.create_index(name, _REQUEST, ["is_template"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _REQUEST in inspector.get_table_names():
        indexes = {i["name"] for i in inspector.get_indexes(_REQUEST)}
        if f"ix_{_REQUEST}_is_template" in indexes:
            op.drop_index(f"ix_{_REQUEST}_is_template", table_name=_REQUEST)
    for table, column in reversed(_COLUMNS):
        if column.name in _columns(inspector, table):
            op.drop_column(table, column.name)
