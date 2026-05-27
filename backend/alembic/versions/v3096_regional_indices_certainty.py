# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Cost Intelligence: regional indices + cost-item usage telemetry.

v3.12.0 Stream B — gives the cost database an RSMeans-like regional
adjustment matrix (region × category factors) plus a per-item usage
ledger that backs the green / yellow / red "certainty" badge surfaced
in the BOQ rate picker.

Two strictly-additive tables:

* ``oe_regional_indices`` — region/category cost-factor matrix. One row
  per (``region_code``, ``category``, ``subcategory``, ``effective_date``)
  triple. Multiple rows for the same region+category are allowed when
  ``effective_date`` differs so escalation feeds (v3.13.0) can append
  quarter-on-quarter snapshots without dropping history. Indexed on
  ``(region_code, category)`` because the lookup is always scoped to a
  single region + a single category at adjustment time.

* ``oe_cost_item_usage`` — append-only log of "this rate was applied to
  this BOQ position at this moment for this rate". Read pattern is "give
  me the most recent N rows for cost_item_id X" so the index is
  ``(cost_item_id, used_at DESC)``. A second index on ``project_id``
  supports per-project usage drill-downs (deferred to v3.13.0). No FK
  on ``project_id`` so the table stays independent of project-level
  retention policies — a deleted project leaves orphan usage rows
  that the badge logic simply ignores.

Idempotent — inspector-guarded so re-runs on a partially migrated DB
skip already-present columns/indexes. SQLite-safe via GUID()→VARCHAR(36)
and Numeric stored as REAL.

Revision ID: v3096_regional_indices_certainty
Revises: v3095_merge_wave34_heads
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3096_regional_indices_certainty"
down_revision: Union[str, Sequence[str], None] = "v3095_merge_wave34_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REGIONAL_TABLE = "oe_regional_indices"
_USAGE_TABLE = "oe_cost_item_usage"
_COST_ITEM_TABLE = "oe_costs_item"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create the regional-indices + cost-item-usage tables."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    # ── oe_regional_indices ───────────────────────────────────────────────
    if not _has_table(inspector, _REGIONAL_TABLE):
        op.create_table(
            _REGIONAL_TABLE,
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
            sa.Column("region_code", sa.String(64), nullable=False),
            # "concrete" | "steel" | "labor" | "mep" | "finishes" | "sitework"
            sa.Column("category", sa.String(64), nullable=False),
            # Optional finer slice (e.g. "rebar" under "steel"). NULL when
            # the row covers the whole category — that's the common case.
            sa.Column("subcategory", sa.String(64), nullable=True),
            # 1.0 baseline. Berlin = 1.0, Munich ≈ 1.12, NYC ≈ 1.45.
            sa.Column(
                "factor",
                sa.Numeric(8, 4),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            # Free-text provenance ("OE_v3.12_seed_2026Q2", "BCIS_2026Q1", ...)
            sa.Column("source", sa.String(128), nullable=False, server_default=""),
            # Quarterly snapshots: 2026-01-01, 2026-04-01, 2026-07-01, ...
            sa.Column("effective_date", sa.Date(), nullable=False),
            sa.UniqueConstraint(
                "region_code",
                "category",
                "subcategory",
                "effective_date",
                name="uq_oe_regional_indices_region_cat_sub_date",
            ),
        )

        existing_ix = _existing_index_names(inspector, _REGIONAL_TABLE)
        ix_region_cat = "ix_oe_regional_indices_region_category"
        if ix_region_cat not in existing_ix:
            try:
                op.create_index(
                    ix_region_cat,
                    _REGIONAL_TABLE,
                    ["region_code", "category"],
                )
            except sa.exc.OperationalError:
                pass

    # ── oe_cost_item_usage ────────────────────────────────────────────────
    if not _has_table(inspector, _USAGE_TABLE):
        op.create_table(
            _USAGE_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "cost_item_id",
                guid_type,
                sa.ForeignKey(f"{_COST_ITEM_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # No FK — project module may be tenant-isolated; we just need
            # the id for drill-down filtering.
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column(
                "used_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("used_by", guid_type, nullable=True),
            # Captured rate at apply-time so historical exports replay
            # exactly what the estimator saw, even if the catalogue is
            # later re-imported.
            sa.Column(
                "unit_rate_at_use",
                sa.Numeric(18, 4),
                nullable=False,
                server_default=sa.text("0"),
            ),
            # "boq" | "assembly" | "tender"
            sa.Column(
                "context",
                sa.String(32),
                nullable=False,
                server_default="boq",
            ),
        )

        existing_ix = _existing_index_names(inspector, _USAGE_TABLE)
        # Primary read path: certainty badge fetches the latest N rows
        # for a given cost item. Use descending order so the index can
        # satisfy ``ORDER BY used_at DESC LIMIT N`` without a temp sort.
        ix_item_time = "ix_oe_cost_item_usage_item_time"
        if ix_item_time not in existing_ix:
            try:
                op.create_index(
                    ix_item_time,
                    _USAGE_TABLE,
                    ["cost_item_id", sa.text("used_at DESC")],
                )
            except (sa.exc.OperationalError, sa.exc.CompileError):
                # SQLite < 3.27 doesn't accept DESC in CREATE INDEX; fall
                # back to a plain index — the planner still uses it and
                # the trailing sort cost is negligible at our row counts.
                try:
                    op.create_index(
                        ix_item_time,
                        _USAGE_TABLE,
                        ["cost_item_id", "used_at"],
                    )
                except sa.exc.OperationalError:
                    pass

        ix_project = "ix_oe_cost_item_usage_project_id"
        if ix_project not in existing_ix:
            try:
                op.create_index(ix_project, _USAGE_TABLE, ["project_id"])
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    """Drop the cost-item-usage + regional-indices tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _USAGE_TABLE):
        existing_ix = _existing_index_names(inspector, _USAGE_TABLE)
        for ix in (
            "ix_oe_cost_item_usage_item_time",
            "ix_oe_cost_item_usage_project_id",
        ):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_USAGE_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_USAGE_TABLE)

    if _has_table(inspector, _REGIONAL_TABLE):
        existing_ix = _existing_index_names(inspector, _REGIONAL_TABLE)
        ix_region_cat = "ix_oe_regional_indices_region_category"
        if ix_region_cat in existing_ix:
            try:
                op.drop_index(ix_region_cat, table_name=_REGIONAL_TABLE)
            except sa.exc.OperationalError:
                pass
        op.drop_table(_REGIONAL_TABLE)
