# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""costmodel — snapshot ``(project_id, period)`` uniqueness.

R5 audit (May 2026): ``create_snapshot`` accepted multiple rows for the
same ``(project_id, period)``. ``get_latest_for_project`` then picked
one arbitrarily and downstream EVM rollups flapped between competing
values. The service now rejects duplicates with 409; this migration
adds the corresponding DB-level guard so a race or a raw repo call
cannot bypass it.

Also widens ``period`` from VARCHAR(10) to VARCHAR(40) so what-if
scenarios — which now store their snapshot row with a
``wif:<short-id>:YYYY-MM`` key to avoid colliding with real monthly
snapshots — fit the column.

Migration is wrapped in ``batch_alter_table`` for SQLite compatibility
and uses inspector guards so a re-run is a no-op.

Down-revision: v3107_costmodel_idempotency.

Revision ID: v3108_costmodel_snapshot_unique
Revises: v3107_costmodel_idempotency
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3108_costmodel_snapshot_unique"
down_revision: Union[str, Sequence[str], None] = "v3107_costmodel_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Inspector helpers ───────────────────────────────────────────────────


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


# ── upgrade ─────────────────────────────────────────────────────────────


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "oe_costmodel_snapshot"):
        return  # Fresh install — Base.metadata.create_all already applied.

    # ── Widen period column from 10 → 40 chars ─────────────────────────
    # batch_alter_table handles SQLite's lack of ALTER COLUMN.
    with op.batch_alter_table("oe_costmodel_snapshot") as batch_op:
        batch_op.alter_column(
            "period",
            existing_type=sa.String(length=10),
            type_=sa.String(length=40),
            existing_nullable=False,
        )

    # ── Dedupe pre-existing duplicate periods ──────────────────────────
    # Keep the oldest snapshot per (project_id, period). On fresh installs
    # this is a no-op.
    op.execute(
        sa.text(
            """
            DELETE FROM oe_costmodel_snapshot
            WHERE id IN (
                SELECT b.id FROM oe_costmodel_snapshot b
                JOIN (
                    SELECT project_id, period,
                           MIN(created_at) AS keep_at
                    FROM oe_costmodel_snapshot
                    GROUP BY project_id, period
                    HAVING COUNT(*) > 1
                ) k
                ON b.project_id = k.project_id
                AND b.period = k.period
                AND b.created_at > k.keep_at
            )
            """
        )
    )

    # ── Unique (project_id, period) ────────────────────────────────────
    inspector = sa.inspect(bind)  # refresh after batch_alter_table
    if not _has_index(
        inspector,
        "oe_costmodel_snapshot",
        "uq_oe_costmodel_snapshot_project_period",
    ):
        op.create_index(
            "uq_oe_costmodel_snapshot_project_period",
            "oe_costmodel_snapshot",
            ["project_id", "period"],
            unique=True,
        )


# ── downgrade ───────────────────────────────────────────────────────────


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(
        inspector,
        "oe_costmodel_snapshot",
        "uq_oe_costmodel_snapshot_project_period",
    ):
        op.drop_index(
            "uq_oe_costmodel_snapshot_project_period",
            table_name="oe_costmodel_snapshot",
        )

    if _has_table(inspector, "oe_costmodel_snapshot"):
        with op.batch_alter_table("oe_costmodel_snapshot") as batch_op:
            batch_op.alter_column(
                "period",
                existing_type=sa.String(length=40),
                type_=sa.String(length=10),
                existing_nullable=False,
            )
