# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3101 — case-insensitive index on oe_crm_lead.contact_email for dedup.

The Round-5 CRM audit added a lead-dedup pre-check in
``CrmService.create_lead`` to translate concurrent inbound webhooks for the
same email address into a deterministic 409 instead of a duplicate-row
silent-success. The pre-check runs ``find_by_email`` which does
``SELECT ... WHERE LOWER(contact_email) = :email`` — without this
covering index that's a full table scan on the hot path.

Plain-column index (not functional) for portability between SQLite and
PostgreSQL through alembic; PG planner still uses it for prefix scans on
the ``LOWER(...)`` query.

Revision ID: v3101_crm
Revises: v3100_sched
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3101_crm"
down_revision: Union[str, Sequence[str], None] = "v3100_sched"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_crm_lead"
_COLUMN = "contact_email"
_INDEX = "ix_oe_crm_lead_contact_email"


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, col: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return col in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if (
        _TABLE in inspector.get_table_names()
        and _has_column(inspector, _TABLE, _COLUMN)
        and not _has_index(inspector, _TABLE, _INDEX)
    ):
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
