# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""reporting - a generated report reaches the client portal only once published.

Two nullable columns on ``oe_reporting_generated``: ``published_at`` (when a
person released the report to the client portal) and ``published_by``. The
portal lists and serves only rows with ``published_at`` set, so a draft that
still carries internal notes stays internal.

DDL only, nothing is backfilled, on purpose: reports generated before this
revision were never reviewed for the client, so they start unpublished and a
person releases the ones the client should see. ``published_by`` is plain
``VARCHAR(36)`` with no foreign key, matching ``GUID`` and the cross-module
convention.

This one does NOT need running by hand. The boot schema heal adds missing
nullable columns (``ADD COLUMN IF NOT EXISTS``), so a running install gains
both columns when it boots the new code. Inspector-guarded, so an install whose
schema came from ``create_all`` plus the heal reaches this revision and adds
nothing.

Revision ID: v52_reporting_report_published
Revises: v51_tendering_bid_invitation
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v52_reporting_report_published"
down_revision: Union[str, Sequence[str], None] = "v51_tendering_bid_invitation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_reporting_generated"
_COLUMNS = (
    ("published_at", sa.DateTime(timezone=True)),
    ("published_by", sa.String(length=36)),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name, type_ in _COLUMNS:
        if name not in present:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name, _type in reversed(_COLUMNS):
        if name in present:
            op.drop_column(_TABLE, name)
