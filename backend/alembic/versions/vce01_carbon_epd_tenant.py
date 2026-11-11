# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""carbon: tenant owner on EPD records

Adds the nullable, indexed ``tenant_id`` to ``oe_carbon_epd_record`` so user-added
(``source=custom``) records are private to their tenant. Additive: a running
install gets it from the boot heal; a deliberate ``alembic upgrade`` applies it too.
No backfill: EPD records carry no creator column, so existing custom rows keep
NULL and stay hidden until an admin assigns them.

Revision ID: vce01_carbon_epd_tenant
Revises: vpf01_project_folder_url
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vce01_carbon_epd_tenant"
down_revision: str | Sequence[str] | None = "vpf01_project_folder_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_carbon_epd_record"
_INDEX = "ix_oe_carbon_epd_record_tenant_id"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if "tenant_id" not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column("tenant_id", sa.String(length=64), nullable=True))
    if _INDEX not in {i["name"] for i in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["tenant_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _INDEX in {i["name"] for i in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if "tenant_id" in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, "tenant_id")
