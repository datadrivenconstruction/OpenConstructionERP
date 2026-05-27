"""v2.9.18 — RiskItem.owner_user_id (FK to oe_users_user).

Promotes the risk register's free-text ``owner_name`` field to a proper
User foreign key so we can drive notifications, @mentions and ownership
analytics from a structured reference. ``owner_name`` is kept around as
a free-text fallback for legacy / unstructured rows — the column is
harmless and lets the picker degrade gracefully when an imported risk
lists an external owner who isn't a registered user.

Inspector-guarded so re-running on an already-migrated DB is a no-op.
Reversible: drops the index and the column on downgrade.

Revision ID: v2918_risk_owner_user_id
Revises: v2917_po_number_unique
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2918_risk_owner_user_id"
down_revision: Union[str, Sequence[str], None] = "v2917_po_number_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_risk_register"
_COLUMN = "owner_user_id"
_INDEX = "ix_oe_risk_register_owner_user_id"
_FK = "fk_oe_risk_register_owner_user_id_users"


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


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if _has_column(inspector, _TABLE, _COLUMN):
        return

    # batch_alter_table is required for SQLite to add a column with a FK.
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(
            sa.Column(
                _COLUMN,
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", name=_FK, ondelete="SET NULL"),
                nullable=True,
            )
        )

    if not _has_index(inspector, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if _has_index(inspector, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_column(inspector, _TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
