# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash Signature + Smart Issues (v41).

Adds the persistent clash-identity layer on top of the run-scoped
``oe_clash_result`` table:

* ``oe_clash_issue`` — one row per signature-per-project. Tracks the
  smart-issue lifecycle (new → persisted → resolved → archived; or
  ignored when a suppression is active), first-/last-/resolved-run
  pointers, assignee, due date, priority, project-local server-assigned
  id (``CLASH-042``-style), tags + signature_quality.
* ``oe_clash_suppression`` — per-project "ignore this signature" rule.
  Unique on (project_id, signature_hash); presence flips every matching
  ``ClashIssue`` to ``ignored`` and prevents it resurfacing on re-runs.

Also extends:

* ``oe_clash_result`` with ``signature_hash`` (40-hex SHA-1),
  ``issue_id`` (nullable FK to ``oe_clash_issue``), ``signature_quality``
  (strong | weak) and ``tolerance_at_signature_time_mm``.
* ``oe_clash_run`` with ``spatial_grid_mm`` (signature centroid bucket;
  default 500 mm) so a coordinator can dial the precision per run.

Idempotent — every table/column/index op is inspector-guarded so a
re-run on a partially-migrated DB skips already-present objects. Safe
on both the SQLite dev DB (``GUID()`` impls as ``VARCHAR(36)``) and the
Postgres prod DB (native ``UUID``).

Revision ID: v41_clash_signature_smart_issues
Revises: v40_fieldreports_uuid_typing
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v41_clash_signature_smart_issues"
down_revision: Union[str, Sequence[str], None] = "v40_fieldreports_uuid_typing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ISSUE_TABLE = "oe_clash_issue"
_SUPPRESSION_TABLE = "oe_clash_suppression"
_RESULT_TABLE = "oe_clash_result"
_RUN_TABLE = "oe_clash_run"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create smart-issue tables + extend result/run with signature columns."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    # ── oe_clash_issue ──
    if not _has_table(inspector, _ISSUE_TABLE):
        op.create_table(
            _ISSUE_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("signature_hash", sa.String(40), nullable=False),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default="new",
            ),
            sa.Column("first_seen_run_id", guid_type, nullable=False),
            sa.Column("last_seen_run_id", guid_type, nullable=False),
            sa.Column("resolved_run_id", guid_type, nullable=True),
            sa.Column(
                "missing_run_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("assignee_id", guid_type, nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column(
                "priority",
                sa.String(16),
                nullable=False,
                server_default="medium",
            ),
            sa.Column(
                "server_assigned_id",
                sa.String(32),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "tags",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column(
                "signature_quality",
                sa.String(8),
                nullable=False,
                server_default="strong",
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["oe_projects_project.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["first_seen_run_id"],
                [f"{_RUN_TABLE}.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["last_seen_run_id"],
                [f"{_RUN_TABLE}.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["resolved_run_id"],
                [f"{_RUN_TABLE}.id"],
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint(
                "project_id",
                "signature_hash",
                name="uq_clash_issue_project_sig",
            ),
            sa.UniqueConstraint(
                "project_id",
                "server_assigned_id",
                name="uq_clash_issue_project_serverid",
            ),
        )
        existing_ix = _existing_index_names(inspector, _ISSUE_TABLE)
        for ix_name, cols in (
            ("ix_clash_issue_project", ["project_id"]),
            ("ix_clash_issue_project_status", ["project_id", "status"]),
            (
                "ix_clash_issue_project_sig",
                ["project_id", "signature_hash"],
            ),
        ):
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, _ISSUE_TABLE, cols)
                except sa.exc.OperationalError:
                    pass

    # ── oe_clash_suppression ──
    if not _has_table(inspector, _SUPPRESSION_TABLE):
        op.create_table(
            _SUPPRESSION_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("signature_hash", sa.String(40), nullable=False),
            sa.Column(
                "reason",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("suppressed_by_user_id", guid_type, nullable=True),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["oe_projects_project.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "project_id",
                "signature_hash",
                name="uq_clash_suppression_project_sig",
            ),
        )
        existing_ix = _existing_index_names(inspector, _SUPPRESSION_TABLE)
        for ix_name, cols in (
            ("ix_clash_suppression_project", ["project_id"]),
            (
                "ix_clash_suppression_project_sig",
                ["project_id", "signature_hash"],
            ),
        ):
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, _SUPPRESSION_TABLE, cols)
                except sa.exc.OperationalError:
                    pass

    # ── oe_clash_run.spatial_grid_mm ──
    if _has_table(inspector, _RUN_TABLE) and not _has_column(inspector, _RUN_TABLE, "spatial_grid_mm"):
        with op.batch_alter_table(_RUN_TABLE) as batch:
            batch.add_column(
                sa.Column(
                    "spatial_grid_mm",
                    sa.Integer(),
                    nullable=False,
                    server_default="500",
                )
            )

    # ── oe_clash_result extensions ──
    if _has_table(inspector, _RESULT_TABLE):
        new_cols: list[tuple[str, sa.Column]] = []
        if not _has_column(inspector, _RESULT_TABLE, "signature_hash"):
            new_cols.append(
                (
                    "signature_hash",
                    sa.Column(
                        "signature_hash",
                        sa.String(40),
                        nullable=False,
                        server_default="",
                    ),
                )
            )
        if not _has_column(inspector, _RESULT_TABLE, "issue_id"):
            new_cols.append(
                (
                    "issue_id",
                    sa.Column("issue_id", guid_type, nullable=True),
                )
            )
        if not _has_column(inspector, _RESULT_TABLE, "signature_quality"):
            new_cols.append(
                (
                    "signature_quality",
                    sa.Column(
                        "signature_quality",
                        sa.String(8),
                        nullable=False,
                        server_default="strong",
                    ),
                )
            )
        if not _has_column(inspector, _RESULT_TABLE, "tolerance_at_signature_time_mm"):
            new_cols.append(
                (
                    "tolerance_at_signature_time_mm",
                    sa.Column(
                        "tolerance_at_signature_time_mm",
                        sa.Float(),
                        nullable=False,
                        server_default="10.0",
                    ),
                )
            )
        if new_cols:
            with op.batch_alter_table(_RESULT_TABLE) as batch:
                for _, col in new_cols:
                    batch.add_column(col)
        # Indexes (idempotent).
        inspector = sa.inspect(bind)  # refresh after ALTER
        existing_ix = _existing_index_names(inspector, _RESULT_TABLE)
        for ix_name, cols in (
            (
                "ix_clash_result_run_sighash",
                ["run_id", "signature_hash"],
            ),
            ("ix_clash_result_issue", ["issue_id"]),
        ):
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, _RESULT_TABLE, cols)
                except sa.exc.OperationalError:
                    pass


def downgrade() -> None:
    """Drop the smart-issue tables + revert the result/run extensions."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Drop result indexes / columns ──
    if _has_table(inspector, _RESULT_TABLE):
        existing_ix = _existing_index_names(inspector, _RESULT_TABLE)
        for ix in ("ix_clash_result_run_sighash", "ix_clash_result_issue"):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_RESULT_TABLE)
                except sa.exc.OperationalError:
                    pass
        with op.batch_alter_table(_RESULT_TABLE) as batch:
            for col in (
                "tolerance_at_signature_time_mm",
                "signature_quality",
                "issue_id",
                "signature_hash",
            ):
                if _has_column(inspector, _RESULT_TABLE, col):
                    try:
                        batch.drop_column(col)
                    except sa.exc.OperationalError:
                        pass

    # ── Drop run.spatial_grid_mm ──
    if _has_column(inspector, _RUN_TABLE, "spatial_grid_mm"):
        with op.batch_alter_table(_RUN_TABLE) as batch:
            try:
                batch.drop_column("spatial_grid_mm")
            except sa.exc.OperationalError:
                pass

    # ── Drop the new tables ──
    if _has_table(inspector, _SUPPRESSION_TABLE):
        existing_ix = _existing_index_names(inspector, _SUPPRESSION_TABLE)
        for ix in (
            "ix_clash_suppression_project",
            "ix_clash_suppression_project_sig",
        ):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_SUPPRESSION_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_SUPPRESSION_TABLE)

    if _has_table(inspector, _ISSUE_TABLE):
        existing_ix = _existing_index_names(inspector, _ISSUE_TABLE)
        for ix in (
            "ix_clash_issue_project",
            "ix_clash_issue_project_status",
            "ix_clash_issue_project_sig",
        ):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_ISSUE_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_ISSUE_TABLE)
