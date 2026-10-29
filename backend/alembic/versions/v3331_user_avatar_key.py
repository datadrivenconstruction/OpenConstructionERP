# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""users​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - profile photo storage key.

Adds the nullable ``avatar_key`` column to ``oe_users_user``. It holds the
storage key of the user's 256 px profile photo; NULL means no photo and the UI
falls back to initials. Inspector-guarded, so a fresh install whose table
``create_all`` already built is a no-op.

Revision ID: v3331_user_avatar_key
Revises: v200_project_color
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3331_user_avatar_key"
down_revision: str | Sequence[str] | None = "v200_project_color"
branch_labels = None
depends_on = None

_TABLE = "oe_users_user"
_COLUMN = "avatar_key"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return True
    return any(c["name"] == _COLUMN for c in inspector.get_columns(_TABLE))


def upgrade() -> None:
    if not _has_column():
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(255), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names() and any(c["name"] == _COLUMN for c in inspector.get_columns(_TABLE)):
        op.drop_column(_TABLE, _COLUMN)
