# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""users: keep the secondary (Hijri) calendar choice on the account.

Adds one nullable column ``secondary_calendar`` to ``oe_users_user``. NULL means the
user never chose (the market default applies); ``none`` and ``hijri`` are choices.
Additive and idempotent (inspector-guarded). Production is deployed by ``create_all``
plus ``alembic stamp head``, so on a running install this revision must be EXECUTED
(``alembic upgrade``), not stamped, for the column to appear.

Revision ID: v3344_user_secondary_calendar
Revises: v3343_measurement_book_and_bbs
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3344_user_secondary_calendar"
down_revision: str | Sequence[str] | None = "v3343_measurement_book_and_bbs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_users_user"
_COLUMN = "secondary_calendar"


def _has_column(insp: sa.engine.reflection.Inspector) -> bool:
    return _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE in insp.get_table_names() and not _has_column(insp):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(10), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE in insp.get_table_names() and _has_column(insp):
        op.drop_column(_TABLE, _COLUMN)
