# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""project: external folder link

Adds the nullable ``external_folder_url`` to ``oe_projects_project``. Additive:
a running install gets it from the boot heal; a deliberate ``alembic upgrade``
applies it too.

Revision ID: vpf01_project_folder_url
Revises: vsm01_sensor_manual_readings
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vpf01_project_folder_url"
down_revision: str | Sequence[str] | None = "vsm01_sensor_manual_readings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_projects_project"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if "external_folder_url" not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column("external_folder_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if "external_folder_url" in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, "external_folder_url")
