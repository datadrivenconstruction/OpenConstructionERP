# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev — Snag deep integration (task #156).

Adds five nullable / default-safe columns to ``oe_property_dev_snag``:

    buyer_id              GUID, nullable, FK -> oe_property_dev_buyer.id
    category              String(40), NOT NULL, server_default='general'
    cost_impact           Numeric(18, 2), NOT NULL, server_default='0'
    photos                JSON, NOT NULL, server_default='[]'
    linked_punch_item_id  GUID, nullable

Adds two indexes:

    ix_oe_property_dev_snag_buyer_id
    ix_oe_property_dev_snag_category

Lesson from #154: every NOT NULL column MUST ship a ``server_default``
so SQLite ``create_all`` and Postgres ALTER both fill the existing
rows. The defaults match the SQLAlchemy model declarations exactly.

SQLite gets ``batch_alter_table`` so the ALTERs execute via copy +
swap, matching the v3103 pattern. Strictly additive and
inspector-guarded so a fresh install with ``create_all`` already
applied is a no-op.

Down-revision: v3106_geo_hub_init.

Revision ID: v3107_propdev_snag_buyer_cost_photos
Revises: v3106_geo_hub_init
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3110_propdev_snag_buyer_cost_photos"
down_revision: Union[str, Sequence[str], None] = "v3109_costmodel_geo_merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_property_dev_snag"


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


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has_table(inspector, _TABLE):
        # Fresh install — create_all already populated everything.
        return

    add_buyer_id = not _has_column(inspector, _TABLE, "buyer_id")
    add_category = not _has_column(inspector, _TABLE, "category")
    add_cost_impact = not _has_column(inspector, _TABLE, "cost_impact")
    add_photos = not _has_column(inspector, _TABLE, "photos")
    add_link = not _has_column(inspector, _TABLE, "linked_punch_item_id")

    needs_any = add_buyer_id or add_category or add_cost_impact or add_photos or add_link

    if needs_any:
        with op.batch_alter_table(_TABLE) as batch:
            if add_buyer_id:
                batch.add_column(
                    sa.Column("buyer_id", guid, nullable=True),
                )
            if add_category:
                batch.add_column(
                    sa.Column(
                        "category",
                        sa.String(40),
                        nullable=False,
                        server_default="general",
                    ),
                )
            if add_cost_impact:
                batch.add_column(
                    sa.Column(
                        "cost_impact",
                        sa.Numeric(18, 2),
                        nullable=False,
                        server_default="0",
                    ),
                )
            if add_photos:
                batch.add_column(
                    sa.Column(
                        "photos",
                        sa.JSON(),
                        nullable=False,
                        server_default="[]",
                    ),
                )
            if add_link:
                batch.add_column(
                    sa.Column("linked_punch_item_id", guid, nullable=True),
                )

    # Re-inspect after the batch so the index probe sees the new columns.
    inspector = sa.inspect(bind)
    if not _has_index(inspector, _TABLE, "ix_oe_property_dev_snag_buyer_id"):
        op.create_index(
            "ix_oe_property_dev_snag_buyer_id",
            _TABLE,
            ["buyer_id"],
        )
    if not _has_index(inspector, _TABLE, "ix_oe_property_dev_snag_category"):
        op.create_index(
            "ix_oe_property_dev_snag_category",
            _TABLE,
            ["category"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    if _has_index(inspector, _TABLE, "ix_oe_property_dev_snag_buyer_id"):
        op.drop_index("ix_oe_property_dev_snag_buyer_id", table_name=_TABLE)
    if _has_index(inspector, _TABLE, "ix_oe_property_dev_snag_category"):
        op.drop_index("ix_oe_property_dev_snag_category", table_name=_TABLE)

    with op.batch_alter_table(_TABLE) as batch:
        for col in (
            "buyer_id",
            "category",
            "cost_impact",
            "photos",
            "linked_punch_item_id",
        ):
            if _has_column(inspector, _TABLE, col):
                batch.drop_column(col)
