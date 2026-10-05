# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""projects - record whether the client is a public buyer.

One nullable column on ``oe_projects_project``: ``works``, ``'public'`` or
``'private'``. Where a country's retention law follows the client, the
contract defaults read it: a French public contract starts from the Code de la
commande publique (R2191-32 to R2191-42), private works from loi n° 71-584.

DDL only, nothing is backfilled, on purpose: no project recorded its client's
status before this revision, so every existing project starts as not recorded
(NULL) and keeps the country's neutral figures until a person says which.

This one does NOT need running by hand. The boot schema heal adds missing
nullable columns (``ADD COLUMN IF NOT EXISTS``), so a running install gains
the column when it boots the new code. Inspector-guarded, so an install whose
schema came from ``create_all`` plus the heal reaches this revision and adds
nothing.

Revision ID: v53_projects_works
Revises: v52_reporting_report_published
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v53_projects_works"
down_revision: Union[str, Sequence[str], None] = "v52_reporting_report_published"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_projects_project"
_COLUMN = "works"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=16), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
