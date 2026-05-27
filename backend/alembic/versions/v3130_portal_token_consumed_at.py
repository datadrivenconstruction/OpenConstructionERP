# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev: buyer-portal magic-link single-use redemption marker.

Adds the nullable ``consumed_at`` timestamp column to
``oe_propdev_portal_token`` so the buyer-portal ``/verify/`` endpoint
can enforce single-use semantics (industry standard — Slack / Notion /
Linear). The column is NULL on issue and is flipped to ``NOW()`` by a
single atomic SQL UPDATE (``WHERE consumed_at IS NULL``) the first
time the magic-link is redeemed. A second / concurrent verify of the
same token cannot succeed — the DB-level race-safety is what gives us
the single-use guarantee, not a Python read-then-write.

Why a new column instead of overloading ``revoked_at``: the two
states are semantically different.

* ``revoked_at`` = "the manager / operator killed this link".
* ``consumed_at`` = "the buyer redeemed this link via /verify/".

Splitting them lets the manager UI keep "active links" (where
``revoked_at IS NULL``) display meaningful counts even after the buyer
has logged in once, and lets the audit report show
"links redeemed but never revoked" vs "links revoked before redemption".

Nullable with ``server_default=None`` — existing rows are NOT
back-filled because they were issued under the multi-use contract; we
treat them as "never consumed" (NULL) and they continue to verify
exactly once before being marked consumed. The fresh-install lock
cascade memory (v3119) doesn't apply here because the column is
nullable.

Idempotent. Down-migration drops the column cleanly.

Revision ID: v3130_portal_token_consumed_at
Revises: v3129_money_decimal_sweep
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3130_portal_token_consumed_at"
down_revision: Union[str, Sequence[str], None] = "v3129_money_decimal_sweep"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_propdev_portal_token"
_COLUMN = "consumed_at"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # If the host table is missing (very fresh install where v3126 hasn't
    # run yet because the user is jumping straight to the latest head),
    # nothing to add — the model definition will create the column via
    # ``create_all``. Safe no-op.
    if not _has_table(inspector, _TABLE):
        return

    if not _has_column(inspector, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=None,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, _TABLE, _COLUMN):
        # SQLite supports drop_column natively from SQLAlchemy 2.x via the
        # batch operations; on PG it's a plain DDL. The plain ``drop_column``
        # works on both for this nullable, default-NULL column.
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_column(_COLUMN)
