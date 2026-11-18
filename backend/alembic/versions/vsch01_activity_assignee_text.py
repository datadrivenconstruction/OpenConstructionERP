"""schedule - an activity's responsible person can be a name typed as written.

One nullable column on ``oe_schedule_activity``: ``assignee_text``. The table's
assignee cell picks a contact (``assignee_id``) or keeps the name typed for a
person who is not in the contacts. Only one of the two holds a value.

Nothing is backfilled. This one does NOT need running by hand: the boot
schema heal adds a missing nullable column, and the add is inspector-guarded,
so an install whose schema came from ``create_all`` plus the heal reaches
this revision and adds nothing.

Revision ID: vsch01_activity_assignee_text
Revises: vsub01_agreement_documents
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vsch01_activity_assignee_text"
down_revision: Union[str, Sequence[str], None] = "vsub01_agreement_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_schedule_activity"
_COLUMN = "assignee_text"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=255), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
