# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""geo_hub: address-geocode cache (Nominatim 30-day cache).

Adds ``oe_geo_hub_geocode_cache`` — a tiny key/value table whose key is
the SHA-256 of the normalised address query string and whose value is
the cached Nominatim response (lat / lon / precision / display_name +
optional bbox). Backs the new auto-anchor flow: when a project's
address is set the backend resolves it through this cache before
falling back to OSM Nominatim. A 30-day TTL keeps the cache fresh
without re-hitting Nominatim on every project open.

Following the post-v4.4.1 server-default discipline (memory note on
issue #154): every NOT NULL column ships ``server_default`` so the
``create_all`` fresh-DB path can't trip ``IntegrityError`` from a
seed insert.

Revision ID: v3124_geo_hub_geocode_cache
Revises: v3123_boq_fk_indexes
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3127_geo_hub_geocode_cache"
down_revision: Union[str, Sequence[str], None] = "v3126_propdev_portal_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "oe_geo_hub_geocode_cache"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(TABLE):
        # Idempotent: ``create_all`` already materialised the table on a
        # fresh install. Migration is a no-op in that case.
        return

    op.create_table(
        TABLE,
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "query_hash",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "query_text",
            sa.String(500),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "lat",
            sa.Numeric(10, 7),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "lon",
            sa.Numeric(10, 7),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "precision",
            sa.String(20),
            nullable=False,
            server_default="address",
        ),
        sa.Column(
            "display_name",
            sa.String(500),
            nullable=False,
            server_default="",
        ),
        sa.Column("bbox_min_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("bbox_min_lon", sa.Numeric(10, 7), nullable=True),
        sa.Column("bbox_max_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("bbox_max_lon", sa.Numeric(10, 7), nullable=True),
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="nominatim",
        ),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "hit_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "uq_oe_geo_hub_geocode_cache_query_hash",
        TABLE,
        ["query_hash"],
        unique=True,
    )
    op.create_index(
        "ix_oe_geo_hub_geocode_cache_cached_at",
        TABLE,
        ["cached_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return
    op.drop_index(
        "ix_oe_geo_hub_geocode_cache_cached_at",
        table_name=TABLE,
    )
    op.drop_index(
        "uq_oe_geo_hub_geocode_cache_query_hash",
        table_name=TABLE,
    )
    op.drop_table(TABLE)
