# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""equipment: required tenant scope on the fleet register

Adds ``tenant_id`` to ``oe_equipment_equipment`` as NOT NULL and makes the unit
code unique per tenant instead of globally. Every other fleet table (rentals,
telemetry, devices, utilisation, logs) is reached through its unit, so one column
scopes them all. A unit is linked to projects only through dated rentals.

Backfill rule for a running install: a tenant is the owning user's id
(``app.core.tenant_scope``) and the shipped installs are single-tenant, so every
existing unit gets one default tenant, the oldest active administrator (admins
first, then oldest), or the literal ``default`` when no user exists yet.

This revision backfills rows, so it has to be EXECUTED (``alembic upgrade``), not
stamped. An install that moves its schema at boot gets the nullable column from
the schema heal and the same backfill plus NOT NULL from the registered repair
``equipment_tenant_backfill``.

Downgrade drops the column and restores the global unique code; it fails on a
database where two tenants already use one code, which is intended.

Revision ID: veq01_equipment_tenant
Revises: vpc01_project_country_from_region
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "veq01_equipment_tenant"
down_revision: str | Sequence[str] | None = "vpc01_project_country_from_region"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_equipment_equipment"
_CODE_INDEX = "ix_oe_equipment_equipment_code"
_TENANT_INDEX = "ix_oe_equipment_equipment_tenant_id"
_TENANT_CODE_INDEX = "uq_oe_equipment_equipment_tenant_code"


def _default_tenant(bind: sa.engine.Connection) -> str:
    if "oe_users_user" not in sa.inspect(bind).get_table_names():
        return "default"
    row = bind.execute(
        sa.text(
            "SELECT id FROM oe_users_user WHERE is_active = :active "
            "ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, created_at, id LIMIT 1"
        ),
        {"active": True},
    ).first()
    return str(row[0]) if row else "default"


# data-rewrite-ack: table=oe_equipment_equipment growth=bounded rows=company fleet register, hundreds of units, one UPDATE
# boot-repair: registry=equipment_tenant_backfill
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    columns = {c["name"]: c for c in inspector.get_columns(_TABLE)}
    if "tenant_id" not in columns:
        op.add_column(_TABLE, sa.Column("tenant_id", sa.String(length=64), nullable=True))

    bind.execute(
        sa.text("UPDATE oe_equipment_equipment SET tenant_id = :tenant WHERE tenant_id IS NULL"),
        {"tenant": _default_tenant(bind)},
    )

    inspector = sa.inspect(bind)
    for idx in inspector.get_indexes(_TABLE):
        if idx["column_names"] == ["code"] and idx.get("unique"):
            op.drop_index(idx["name"], table_name=_TABLE)
    for uq in inspector.get_unique_constraints(_TABLE):
        if uq["column_names"] == ["code"] and uq.get("name"):
            op.drop_constraint(uq["name"], _TABLE, type_="unique")
    existing = {i["name"] for i in sa.inspect(bind).get_indexes(_TABLE)}
    if _CODE_INDEX not in existing:
        op.create_index(_CODE_INDEX, _TABLE, ["code"])
    if _TENANT_INDEX not in existing:
        op.create_index(_TENANT_INDEX, _TABLE, ["tenant_id"])
    if _TENANT_CODE_INDEX not in existing:
        op.create_index(_TENANT_CODE_INDEX, _TABLE, ["tenant_id", "code"], unique=True)

    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(length=64), nullable=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if "tenant_id" not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        return
    existing = {i["name"] for i in inspector.get_indexes(_TABLE)}
    if _TENANT_CODE_INDEX in existing:
        op.drop_index(_TENANT_CODE_INDEX, table_name=_TABLE)
    if _TENANT_INDEX in existing:
        op.drop_index(_TENANT_INDEX, table_name=_TABLE)
    if _CODE_INDEX in existing:
        op.drop_index(_CODE_INDEX, table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("tenant_id")
    op.create_index(_CODE_INDEX, _TABLE, ["code"], unique=True)
