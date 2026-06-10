# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project gross floor area - real cost benchmark portfolio input.

Adds a single strictly-additive nullable column ``gross_floor_area`` to
``oe_projects_project``. The Cost Benchmarks module computes a real
cost-per-m2 figure per project (BOQ grand total divided by area) and
aggregates those into a tenant portfolio distribution, so the platform
can compare a project against the user's own real projects instead of
static reference numbers.

Stored as a decimal-string (String) to match the project money and
quantity columns (``budget_estimate``, ``contract_value``), which keep
full precision regardless of backend and never lose digits through JSON
Number on the client. NULL means area is not recorded yet, in which case
the project is simply skipped by the portfolio aggregation.

The embedded PostgreSQL runtime materialises the schema via ``create_all``
from the models at startup, so this migration is for external-PostgreSQL
deployments that manage schema with Alembic. The change is guarded with an
existence check so a re-run, or a DB the runtime already auto-created, is a
no-op. PostgreSQL-only, no SQLite shims.

Revision ID: v3174_project_gross_floor_area
Revises: v3173_qa_hardening
Create Date: 2026-06-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3174_project_gross_floor_area"
down_revision = "v3173_qa_hardening"
branch_labels = None
depends_on = None


_TABLE = "oe_projects_project"
_COLUMN = "gross_floor_area"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if _has_table(_TABLE) and not _has_column(_TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.String(length=50), nullable=True),
        )


def downgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
