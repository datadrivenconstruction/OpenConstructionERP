# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev: lead source_cost + broker_id + sales-analytics indexes.

Adds the columns the new sales-analytics dashboard endpoints need:

* ``oe_property_dev_lead.source_cost`` (Numeric(15, 2), NULLABLE) — campaign
  spend / pay-per-click invoice attributable to this lead. Drives the
  CPA column on the lead-source-attribution widget. NULL means "unknown
  cost" (the rollup will simply omit a CPA value for that source).
* ``oe_property_dev_lead.broker_id`` (UUID, NULLABLE, FK to broker) —
  assigned broker / agency owning the lead end-to-end. NULL = in-house.
  Drives the per-broker leaderboard.

Plus the composite indexes the analytics endpoints depend on (every
analytics endpoint is window-scoped, so the planner needs an index
covering ``WHERE <fk> = ? AND created_at >= ?`` shapes):

* ``ix_propdev_lead_dev_created`` (development_id, created_at)
* ``ix_propdev_lead_source_created`` (source, created_at)
* ``ix_propdev_lead_broker_created`` (broker_id, created_at)
* ``ix_propdev_reservation_dev_created``
  (plot_id+via-Plot join would suffice but we keep a direct index on
   ``created_at`` for the cohort-retention range scans).
* ``ix_propdev_sales_contract_status_signing`` (status, signing_date)
* ``ix_propdev_handover_completed_at`` (completed_at)

All migrations are idempotent — re-running on a hot DB is a no-op.
Per the perf-discipline established in v3123, postgres indexes are
created with ``CREATE INDEX CONCURRENTLY IF NOT EXISTS`` so the
deployment doesn't take an ACCESS EXCLUSIVE lock on the lead /
reservation tables. SQLite uses the plain ``CREATE INDEX IF NOT
EXISTS`` form (no concurrent-DDL concept).

Revision ID: v3124_propdev_analytics_indexes
Revises: v3123_boq_fk_indexes
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3124_propdev_analytics_indexes"
down_revision: Union[str, Sequence[str], None] = "v3123_boq_fk_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES: list[tuple[str, str, list[str]]] = [
    (
        "oe_property_dev_lead",
        "ix_propdev_lead_dev_created",
        ["development_id", "created_at"],
    ),
    (
        "oe_property_dev_lead",
        "ix_propdev_lead_source_created",
        ["source", "created_at"],
    ),
    (
        "oe_property_dev_lead",
        "ix_propdev_lead_broker_created",
        ["broker_id", "created_at"],
    ),
    (
        "oe_property_dev_reservation",
        "ix_propdev_reservation_created",
        ["created_at"],
    ),
    (
        "oe_property_dev_sales_contract",
        "ix_propdev_sales_contract_status_signing",
        ["status", "signing_date"],
    ),
    (
        "oe_property_dev_handover",
        "ix_propdev_handover_completed_at",
        ["completed_at"],
    ),
]


def _existing_indexes(inspector: sa.Inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def _existing_columns(inspector: sa.Inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # 1) Add the two new columns to oe_property_dev_lead (idempotent —
    # skip if already present, so the migration can be re-run on a hot
    # DB or after a partial failure).
    lead_cols = _existing_columns(inspector, "oe_property_dev_lead")
    if "oe_property_dev_lead" in inspector.get_table_names():
        if "source_cost" not in lead_cols:
            op.add_column(
                "oe_property_dev_lead",
                sa.Column("source_cost", sa.Numeric(15, 2), nullable=True),
            )
        if "broker_id" not in lead_cols:
            op.add_column(
                "oe_property_dev_lead",
                sa.Column("broker_id", sa.CHAR(36), nullable=True),
            )

    # 2) Composite indexes for the analytics endpoints. Same dialect-aware
    # CONCURRENT pattern as v3123_boq_fk_indexes.
    # Refresh inspector cache after add_column above.
    inspector = sa.inspect(bind)
    for table, index_name, columns in _INDEXES:
        existing = _existing_indexes(inspector, table)
        if index_name in existing:
            continue
        if not inspector.has_table(table):
            continue
        # Skip composites that reference a column we just may have failed
        # to add (defensive — only matters on partial alembic failures).
        tbl_cols = _existing_columns(inspector, table)
        if not all(c in tbl_cols for c in columns):
            continue

        col_list = ", ".join(columns)
        if dialect == "postgresql":
            op.execute("COMMIT")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table} ({col_list})")
            op.execute("BEGIN")
        else:
            op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({col_list})")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # Drop indexes first (reverse order).
    for table, index_name, _ in reversed(_INDEXES):
        existing = _existing_indexes(inspector, table)
        if index_name not in existing:
            continue
        if dialect == "postgresql":
            op.execute("COMMIT")
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
            op.execute("BEGIN")
        else:
            op.execute(f"DROP INDEX IF EXISTS {index_name}")

    # Then the columns.
    lead_cols = _existing_columns(inspector, "oe_property_dev_lead")
    if "broker_id" in lead_cols:
        op.drop_column("oe_property_dev_lead", "broker_id")
    if "source_cost" in lead_cols:
        op.drop_column("oe_property_dev_lead", "source_cost")
