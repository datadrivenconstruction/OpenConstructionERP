# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash Wave A4 — Intelligence (rules / clusters / FP loop / suggestions).

Additive schema delta covering every Wave A4 surface in one migration:

* ``oe_clash_run.rules``       — NOT NULL JSON default ``'[]'``.
                                 Per-discipline-pair tolerance rules
                                 the engine consults during the broad
                                 phase (BIM-coordination tool style rule rows).
* ``oe_clash_result.cluster_id`` — nullable Integer. Run-scoped spatial
                                 cluster id assigned by the
                                 post-detection grid-bucket DBSCAN.
* ``oe_clash_cluster``         — new table. AI-derived short label per
                                 ``(run_id, cluster_id)`` so the cluster
                                 chip can render "Cluster #N · <label>".

Merge migration: it carries TWO ``down_revision`` parents because Wave
A2 and Wave A3 each shipped their own ``v3048_*`` revision in parallel.
Alembic treats the tuple as an explicit merge of the two branches, so
the linear ordering stays clean and a fresh ``alembic upgrade head``
applies all three deltas with no manual intervention.

Idempotent: inspector-guarded so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a no-op;
Postgres prod gets the DDL.

Revision ID: v3049_clash_a4_intelligence
Revises: (v3048_clash_a2_metadata, v3048_clash_collab)
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3049_clash_a4_intelligence"
down_revision: Union[str, Sequence[str], None] = (
    "v3048_clash_a2_metadata",
    "v3049_clash_collab",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RUN = "oe_clash_run"
_RESULT = "oe_clash_result"
_CLUSTER = "oe_clash_cluster"
_CLUSTER_RUN_IDX = "ix_clash_cluster_run"
_CLUSTER_RUN_CLUSTER_IDX = "ix_clash_cluster_run_cluster"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── oe_clash_run.rules ─────────────────────────────────────────────
    if _has_table(inspector, _RUN):
        run_cols = {c["name"] for c in inspector.get_columns(_RUN)}
        if "rules" not in run_cols:
            op.add_column(
                _RUN,
                sa.Column(
                    "rules",
                    sa.JSON(),
                    nullable=False,
                    server_default="[]",
                ),
            )

    # ── oe_clash_result.cluster_id ─────────────────────────────────────
    if _has_table(inspector, _RESULT):
        res_cols = {c["name"] for c in inspector.get_columns(_RESULT)}
        if "cluster_id" not in res_cols:
            op.add_column(
                _RESULT,
                sa.Column("cluster_id", sa.Integer(), nullable=True),
            )

    # ── oe_clash_cluster (lookup table for AI cluster labels) ──────────
    if not _has_table(inspector, _CLUSTER):
        op.create_table(
            _CLUSTER,
            sa.Column("id", sa.CHAR(32), primary_key=True),
            sa.Column(
                "run_id",
                sa.CHAR(32),
                sa.ForeignKey("oe_clash_run.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("cluster_id", sa.Integer(), nullable=False),
            sa.Column(
                "label",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "size",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
        )
        existing_idx = (
            {ix["name"] for ix in inspector.get_indexes(_CLUSTER)} if _has_table(sa.inspect(bind), _CLUSTER) else set()
        )
        if _CLUSTER_RUN_IDX not in existing_idx:
            op.create_index(_CLUSTER_RUN_IDX, _CLUSTER, ["run_id"])
        if _CLUSTER_RUN_CLUSTER_IDX not in existing_idx:
            op.create_index(
                _CLUSTER_RUN_CLUSTER_IDX,
                _CLUSTER,
                ["run_id", "cluster_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _CLUSTER):
        existing_idx = {ix["name"] for ix in inspector.get_indexes(_CLUSTER)}
        if _CLUSTER_RUN_CLUSTER_IDX in existing_idx:
            op.drop_index(_CLUSTER_RUN_CLUSTER_IDX, table_name=_CLUSTER)
        if _CLUSTER_RUN_IDX in existing_idx:
            op.drop_index(_CLUSTER_RUN_IDX, table_name=_CLUSTER)
        op.drop_table(_CLUSTER)

    if _has_table(inspector, _RESULT):
        res_cols = {c["name"] for c in inspector.get_columns(_RESULT)}
        if "cluster_id" in res_cols:
            op.drop_column(_RESULT, "cluster_id")

    if _has_table(inspector, _RUN):
        run_cols = {c["name"] for c in inspector.get_columns(_RUN)}
        if "rules" in run_cols:
            op.drop_column(_RUN, "rules")
