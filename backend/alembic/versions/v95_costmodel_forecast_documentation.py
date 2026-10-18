# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""costmodel forecast documentation - forecast methods, draft and frozen snapshots, line evidence.

Three new tables and five additive columns on the snapshot table, no data rewrite:

* ``oe_costmodel_cost_control_settings``: a project's forecast method and evidence threshold, one row per
  project. A project without a row reads the defaults (best available source, 10 %), so nothing needs a
  backfill.
* ``oe_costmodel_forecast_method``: the method one cost line is read with when someone chose one for it.
* ``oe_costmodel_forecast_snapshot_note``: comment and evidence behind one line of a snapshot.
* ``oe_costmodel_forecast_snapshot``: ``status`` (``draft`` or ``frozen``, existing rows read ``frozen``
  through the server default, which is what they always were), ``frozen_at``, ``frozen_by``,
  ``previous_snapshot_id`` and ``meta``.

Pip and desktop installs never run this revision: ``create_all`` builds the tables and the schema heal adds
the columns on boot. Every step is inspector-guarded, so a database that already has them reaches this
revision without error.

Revision ID: v95_costmodel_forecast_documentation
Revises: v94_payment_release
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.db_types import MoneyType
from app.database import GUID

revision: str = "v95_costmodel_forecast_documentation"
down_revision: str | Sequence[str] | None = "v94_payment_release"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SNAP = "oe_costmodel_forecast_snapshot"
_SETTINGS = "oe_costmodel_cost_control_settings"
_METHOD = "oe_costmodel_forecast_method"
_NOTE = "oe_costmodel_forecast_snapshot_note"

_SNAPSHOT_COLUMNS: tuple[str, ...] = ("status", "frozen_at", "frozen_by", "previous_snapshot_id", "meta")


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _project_fk(name: str) -> sa.Column:
    return sa.Column(
        "project_id",
        GUID(),
        sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE", name=name),
        nullable=False,
    )


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _indexes(bind: sa.engine.Connection, table: str) -> set[str]:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def _ensure_index(bind: sa.engine.Connection, table: str, name: str, cols: list[str]) -> None:
    if name not in _indexes(bind, table):
        op.create_index(name, table, cols)


def _snapshot_columns(bind: sa.engine.Connection) -> None:
    existing = _columns(bind, _SNAP)
    if "status" not in existing:
        op.add_column(_SNAP, sa.Column("status", sa.String(10), nullable=False, server_default="frozen"))
    if "frozen_at" not in existing:
        op.add_column(_SNAP, sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True))
    if "frozen_by" not in existing:
        op.add_column(_SNAP, sa.Column("frozen_by", sa.String(36), nullable=True))
    if "previous_snapshot_id" not in existing:
        op.add_column(_SNAP, sa.Column("previous_snapshot_id", GUID(), nullable=True))
    if "meta" not in existing:
        op.add_column(_SNAP, sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"))


def upgrade() -> None:
    """Add the snapshot columns and create the three tables."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _SNAP in tables:
        _snapshot_columns(bind)

    if _SETTINGS not in tables:
        op.create_table(
            _SETTINGS,
            *_base_columns(),
            _project_fk("fk_costmodel_cc_settings_project"),
            sa.Column("forecast_method", sa.String(20), nullable=False, server_default="best_available"),
            sa.Column("evidence_threshold_amount", MoneyType(), nullable=False, server_default="0"),
            sa.Column("evidence_threshold_pct", sa.Numeric(7, 2), nullable=True, server_default="10"),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_costmodel_cost_control_settings"),
            sa.UniqueConstraint("project_id", name="uq_costmodel_cc_settings_project"),
        )
    _ensure_index(bind, _SETTINGS, "ix_oe_costmodel_cost_control_settings_project_id", ["project_id"])

    if _METHOD not in tables:
        op.create_table(
            _METHOD,
            *_base_columns(),
            _project_fk("fk_costmodel_forecast_method_project"),
            sa.Column(
                "cost_line_id",
                GUID(),
                sa.ForeignKey(
                    "oe_costmodel_cost_line.id",
                    ondelete="CASCADE",
                    name="fk_costmodel_forecast_method_line",
                ),
                nullable=False,
            ),
            sa.Column("method", sa.String(20), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_costmodel_forecast_method"),
            sa.UniqueConstraint("cost_line_id", name="uq_costmodel_forecast_method_line"),
        )
    _ensure_index(bind, _METHOD, "ix_oe_costmodel_forecast_method_project_id", ["project_id"])

    if _NOTE not in tables:
        op.create_table(
            _NOTE,
            *_base_columns(),
            sa.Column(
                "snapshot_id",
                GUID(),
                sa.ForeignKey(
                    f"{_SNAP}.id",
                    ondelete="CASCADE",
                    name="fk_costmodel_snapshot_note_snapshot",
                ),
                nullable=False,
            ),
            sa.Column("row_key", sa.String(80), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_costmodel_forecast_snapshot_note"),
            sa.UniqueConstraint("snapshot_id", "row_key", name="uq_costmodel_snapshot_note_row"),
        )
    _ensure_index(bind, _NOTE, "ix_oe_costmodel_forecast_snapshot_note_snapshot_id", ["snapshot_id"])


def downgrade() -> None:
    """Drop the three tables and the five snapshot columns.

    Every snapshot row stays: a draft reads as an ordinary saved forecast to the code before this revision.
    """
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in (_NOTE, _METHOD, _SETTINGS):
        if table in tables:
            op.drop_table(table)
    if _SNAP in tables:
        existing = _columns(bind, _SNAP)
        drop = [c for c in reversed(_SNAPSHOT_COLUMNS) if c in existing]
        if drop:
            with op.batch_alter_table(_SNAP) as batch:
                for column in drop:
                    batch.drop_column(column)
