# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3099 — subcontractors unique tax_id index (per tenant).

Round-5 subcontractors audit: backfills a unique covering index on
``(tenant_id, tax_id)`` so duplicate subcontractor registrations within
the same tenant return a clean :class:`IntegrityError`.

Idempotent + inspector-guarded.

Revision ID: v3099_subs
Revises: v3098
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3099_subs"
down_revision: Union[str, Sequence[str], None] = "v3098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_subcontractors_subcontractor"
_INDEX = "ix_subs_tenant_tax_id"


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_columns(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    cols: list[str],
) -> bool:
    if table not in inspector.get_table_names():
        return False
    present = {c["name"] for c in inspector.get_columns(table)}
    return all(c in present for c in cols)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if (
        _TABLE in inspector.get_table_names()
        and _has_columns(inspector, _TABLE, ["tenant_id", "tax_id"])
        and not _has_index(inspector, _TABLE, _INDEX)
    ):
        op.create_index(
            _INDEX,
            _TABLE,
            ["tenant_id", "tax_id"],
            unique=False,
            sqlite_where=sa.text("tax_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
