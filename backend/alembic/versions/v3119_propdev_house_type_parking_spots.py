# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""propdev: house-type catalogue — add ``parking_spots`` field.

Adds a single nullable integer column ``parking_spots`` to
``oe_property_dev_house_type_catalogue``. v3118 covered every other
layout / pricing / marketing field requested by the polished
"New house type" modal; parking remained the only missing dimension.

Following the post-v4.4.1 server-default discipline (see memory note on
issue #154): every NOT NULL column ships ``server_default`` so a
``create_all`` fresh-DB path can't trip ``IntegrityError``. Here the
column is NULLABLE so ``server_default`` is moot, but we keep the
idempotent ``in_columns`` guard so the migration is safe to re-run.

Revision ID: v3119_propdev_house_type_parking_spots
Revises: v3118_propdev_house_type_extra_fields
Create Date: 2026-05-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3119_propdev_house_type_parking_spots"
down_revision: Union[str, Sequence[str], None] = "v3118_propdev_house_type_extra_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "oe_property_dev_house_type_catalogue"
COLUMN_NAME = "parking_spots"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(TABLE):
        # v3114 (create_all) will eventually create the table — this is
        # a strictly additive migration, bail out cleanly.
        return

    existing_cols = {c["name"] for c in inspector.get_columns(TABLE)}
    if COLUMN_NAME in existing_cols:
        return

    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(COLUMN_NAME, sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing_cols = {c["name"] for c in inspector.get_columns(TABLE)}
    if COLUMN_NAME not in existing_cols:
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN_NAME)
