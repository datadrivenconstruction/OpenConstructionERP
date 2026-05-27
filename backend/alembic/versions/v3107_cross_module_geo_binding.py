# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""cross-module geo binding — Safety + Punchlist geo_lat/geo_lon.

Adds nullable WGS84 coordinate columns to safety_incident and punchlist_item
so Geo Hub can render HSE / Punchlist pin layers on the project map.

The columns are deliberately nullable with NO server_default — incidents and
punch items that pre-date the column (or are simply not pinned on the map)
must distinguish "no pin" from "pinned at (0, 0)". This sidesteps the same
``IntegrityError on fresh-install snapshot replay`` class that bit us with
``SafetyIncident.osha_recordable`` in #154: nullable + no default means
``Base.metadata.create_all`` and the committed showcase snapshot can both
load without any NOT-NULL collision.

Daily Diary photos already carry ``lat``/``lng`` (predating this work) so
they need no migration — they're surfaced via the Geo Hub layer endpoint
directly.

Strictly additive + inspector-guarded so:
* fresh installs (Base.metadata.create_all already created the columns
  from the updated models) → no-op
* existing installs (older DB without the columns) → columns are added

Down-revision: v3106_geo_hub_init.

Revision ID: v3107_cross_module_geo_binding
Revises: v3106_geo_hub_init
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3107_cross_module_geo_binding"
down_revision: Union[str, Sequence[str], None] = "v3106_geo_hub_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Inspector helpers ───────────────────────────────────────────────────


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


# ── Upgrade ─────────────────────────────────────────────────────────────


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # oe_safety_incident.geo_lat / geo_lon ────────────────────────────────
    if _has_table(inspector, "oe_safety_incident"):
        with op.batch_alter_table("oe_safety_incident") as batch_op:
            if not _has_column(inspector, "oe_safety_incident", "geo_lat"):
                batch_op.add_column(
                    sa.Column("geo_lat", sa.Float(), nullable=True),
                )
            if not _has_column(inspector, "oe_safety_incident", "geo_lon"):
                batch_op.add_column(
                    sa.Column("geo_lon", sa.Float(), nullable=True),
                )

    # oe_punchlist_item.geo_lat / geo_lon ─────────────────────────────────
    if _has_table(inspector, "oe_punchlist_item"):
        with op.batch_alter_table("oe_punchlist_item") as batch_op:
            if not _has_column(inspector, "oe_punchlist_item", "geo_lat"):
                batch_op.add_column(
                    sa.Column("geo_lat", sa.Float(), nullable=True),
                )
            if not _has_column(inspector, "oe_punchlist_item", "geo_lon"):
                batch_op.add_column(
                    sa.Column("geo_lon", sa.Float(), nullable=True),
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "oe_safety_incident"):
        with op.batch_alter_table("oe_safety_incident") as batch_op:
            if _has_column(inspector, "oe_safety_incident", "geo_lon"):
                batch_op.drop_column("geo_lon")
            if _has_column(inspector, "oe_safety_incident", "geo_lat"):
                batch_op.drop_column("geo_lat")

    if _has_table(inspector, "oe_punchlist_item"):
        with op.batch_alter_table("oe_punchlist_item") as batch_op:
            if _has_column(inspector, "oe_punchlist_item", "geo_lon"):
                batch_op.drop_column("geo_lon")
            if _has_column(inspector, "oe_punchlist_item", "geo_lat"):
                batch_op.drop_column("geo_lat")
