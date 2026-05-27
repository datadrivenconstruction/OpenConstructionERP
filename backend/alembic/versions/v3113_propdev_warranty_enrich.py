# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev — WarrantyClaim deep integration.

Extends ``oe_property_dev_warranty_claim`` so the Warranty Claims page
can do more than list-by-buyer. Adds:

    handover_id            GUID, nullable, FK -> oe_property_dev_handover.id (SET NULL)
    source_snag_id         GUID, nullable, FK -> oe_property_dev_snag.id (SET NULL)
    assigned_to_user_id    GUID, nullable (no FK — cross-module loose ref)
    severity               String(20), NOT NULL, server_default='minor'
    photos                 JSON,         NOT NULL, server_default='[]'
    sla_deadline           String(20),   nullable (YYYY-MM-DD)
    resolution_notes       Text,         nullable

Indexes added:

    ix_oe_property_dev_warranty_claim_handover_id
    ix_oe_property_dev_warranty_claim_source_snag_id
    ix_oe_property_dev_warranty_claim_assigned_to_user_id
    ix_oe_property_dev_warranty_claim_severity

Strict v3110-style inspector guards + per-column server_default so the
``no such column`` cascade from #154 cannot reappear. ``batch_alter_table``
is used unconditionally (no-op on Postgres, copy-and-swap on SQLite).

Revision ID: v3113_propdev_warranty_enrich
Revises: v3112_bootstrap_missing_tables
Create Date: 2026-05-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3113_propdev_warranty_enrich"
down_revision: Union[str, Sequence[str], None] = "v3112_bootstrap_missing_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_property_dev_warranty_claim"


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

    add_handover = not _has_column(inspector, _TABLE, "handover_id")
    add_source_snag = not _has_column(inspector, _TABLE, "source_snag_id")
    add_assigned = not _has_column(inspector, _TABLE, "assigned_to_user_id")
    add_severity = not _has_column(inspector, _TABLE, "severity")
    add_photos = not _has_column(inspector, _TABLE, "photos")
    add_sla = not _has_column(inspector, _TABLE, "sla_deadline")
    add_resolution = not _has_column(inspector, _TABLE, "resolution_notes")

    needs_any = any(
        [
            add_handover,
            add_source_snag,
            add_assigned,
            add_severity,
            add_photos,
            add_sla,
            add_resolution,
        ]
    )

    if needs_any:
        with op.batch_alter_table(_TABLE) as batch:
            if add_handover:
                batch.add_column(sa.Column("handover_id", guid, nullable=True))
            if add_source_snag:
                batch.add_column(
                    sa.Column("source_snag_id", guid, nullable=True),
                )
            if add_assigned:
                batch.add_column(
                    sa.Column("assigned_to_user_id", guid, nullable=True),
                )
            if add_severity:
                batch.add_column(
                    sa.Column(
                        "severity",
                        sa.String(20),
                        nullable=False,
                        server_default="minor",
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
            if add_sla:
                batch.add_column(
                    sa.Column("sla_deadline", sa.String(20), nullable=True),
                )
            if add_resolution:
                batch.add_column(
                    sa.Column("resolution_notes", sa.Text(), nullable=True),
                )

    # Re-inspect after the batch so the index probe sees the new columns.
    inspector = sa.inspect(bind)

    for name, col in (
        ("ix_oe_property_dev_warranty_claim_handover_id", "handover_id"),
        ("ix_oe_property_dev_warranty_claim_source_snag_id", "source_snag_id"),
        (
            "ix_oe_property_dev_warranty_claim_assigned_to_user_id",
            "assigned_to_user_id",
        ),
        ("ix_oe_property_dev_warranty_claim_severity", "severity"),
    ):
        if _has_column(inspector, _TABLE, col) and not _has_index(inspector, _TABLE, name):
            op.create_index(name, _TABLE, [col])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    for name in (
        "ix_oe_property_dev_warranty_claim_handover_id",
        "ix_oe_property_dev_warranty_claim_source_snag_id",
        "ix_oe_property_dev_warranty_claim_assigned_to_user_id",
        "ix_oe_property_dev_warranty_claim_severity",
    ):
        if _has_index(inspector, _TABLE, name):
            op.drop_index(name, table_name=_TABLE)

    with op.batch_alter_table(_TABLE) as batch:
        for col in (
            "handover_id",
            "source_snag_id",
            "assigned_to_user_id",
            "severity",
            "photos",
            "sla_deadline",
            "resolution_notes",
        ):
            if _has_column(inspector, _TABLE, col):
                batch.drop_column(col)
