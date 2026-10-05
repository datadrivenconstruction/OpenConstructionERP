"""schedule - a milestone reaches the client portal only when marked for the client.

One column on ``oe_schedule_activity``: ``client_visible``, a boolean that
defaults to false. The client portal lists upcoming milestones from rows with
the flag set, so an internal milestone ("pay the steel supplier", "fix the
crane permit") never lands in front of the client unless a person chose so.

Nothing is backfilled: existing milestones start hidden, the same way
unpublished progress reports do.

This one does NOT need running by hand. The boot schema heal adds the
missing column with its default (``ADD COLUMN IF NOT EXISTS ... DEFAULT``),
the same path ``is_critical`` on this table already takes. Inspector-guarded,
so an install whose schema came from ``create_all`` plus the heal reaches this
revision and adds nothing.

Revision ID: v53_schedule_activity_client_visible
Revises: v52_reporting_report_published
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v53_schedule_activity_client_visible"
down_revision: Union[str, Sequence[str], None] = "v52_reporting_report_published"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_schedule_activity"
_COLUMN = "client_visible"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
