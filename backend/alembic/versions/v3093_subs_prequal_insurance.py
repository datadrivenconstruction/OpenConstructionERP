# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractors — BuildingConnected-style prequal score + insurance tracking.

Wave 4 / T12 — brings ``oe_subcontractors_subcontractor`` toward
BuildingConnected / Procore parity for the three lifecycle gaps that
are still missing on a flat sub record:

* ``prequal_score`` (Integer) — denormalised numeric score derived from
  the most recent prequalification questionnaire. Lets list-view filter
  / sort without joining the questionnaire history table.
* ``prequal_questionnaire`` (JSON) — the last submitted questionnaire
  payload (typically a small dict of Yes/No / multi-choice answers).
* ``prequal_completed_at`` (DateTime) — when the most recent
  questionnaire was submitted, so dashboards can render staleness.
* ``insurance_expiry_date`` (Date) — convenience denorm of the most
  recent insurance certificate's expiry. Indexed for the nightly
  expiry-sweep cron job.
* ``insurance_doc_id`` (GUID) — soft reference to the uploaded
  insurance document (no FK — Documents module may live in a separate
  schema in some deployments).
* ``blocked_reason`` (Text) — free-form text explaining why the sub
  has been blocked from bidding / payment.
* ``is_blocked`` (Boolean, default False) — hard gate; when true the
  sub does not surface in bid lists, can't accept new agreements.

Adds an index on ``insurance_expiry_date`` so the nightly sweep can
seek to "expiring within 30 days" with an index range scan rather
than a full-table read.

Idempotent — inspector-guarded so re-runs on a partially migrated DB
skip already-present columns/indexes. SQLite-safe via
``batch_alter_table``. Fully reversible.

Revision ID: v3093_subs_prequal_insurance
Revises: v3087_merge_wave2_heads
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3093_subs_prequal_insurance"
down_revision: Union[str, Sequence[str], None] = "v3087_merge_wave2_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_subcontractors_subcontractor"
_IX_INSURANCE_EXPIRY = "ix_oe_subcontractors_subcontractor_insurance_expiry_date"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_cols(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Add prequal + insurance + blocked columns to the subcontractor table."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    existing = _existing_cols(inspector, _TABLE)

    # Column name -> SQLAlchemy column factory. All nullable / defaulted so
    # the ALTER works against a populated table on SQLite (which can't add
    # a NOT-NULL column without a default).
    new_columns: list[tuple[str, sa.Column[object]]] = [
        ("prequal_score", sa.Column("prequal_score", sa.Integer(), nullable=True)),
        (
            "insurance_expiry_date",
            sa.Column("insurance_expiry_date", sa.Date(), nullable=True),
        ),
        (
            "insurance_doc_id",
            sa.Column("insurance_doc_id", guid_type, nullable=True),
        ),
        (
            "prequal_questionnaire",
            sa.Column("prequal_questionnaire", sa.JSON(), nullable=True),
        ),
        (
            "prequal_completed_at",
            sa.Column(
                "prequal_completed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        ),
        ("blocked_reason", sa.Column("blocked_reason", sa.Text(), nullable=True)),
        (
            "is_blocked",
            sa.Column(
                "is_blocked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        ),
    ]
    missing = [(name, col) for name, col in new_columns if name not in existing]
    if missing:
        # batch_alter_table is required for SQLite to add multiple columns.
        with op.batch_alter_table(_TABLE) as batch:
            for _name, col in missing:
                batch.add_column(col)

    # Index on insurance_expiry_date — nightly sweep scans "expiring within
    # N days" so we want a range-scan-friendly index. Guarded so re-runs
    # don't error.
    existing_ix = _existing_index_names(inspector, _TABLE)
    if _IX_INSURANCE_EXPIRY not in existing_ix:
        try:
            op.create_index(
                _IX_INSURANCE_EXPIRY,
                _TABLE,
                ["insurance_expiry_date"],
            )
        except sa.exc.OperationalError:
            pass


def downgrade() -> None:
    """Drop the prequal + insurance + blocked columns + supporting index."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    existing_ix = _existing_index_names(inspector, _TABLE)
    if _IX_INSURANCE_EXPIRY in existing_ix:
        try:
            op.drop_index(_IX_INSURANCE_EXPIRY, table_name=_TABLE)
        except sa.exc.OperationalError:
            pass

    existing = _existing_cols(inspector, _TABLE)
    drop_order = (
        "is_blocked",
        "blocked_reason",
        "prequal_completed_at",
        "prequal_questionnaire",
        "insurance_doc_id",
        "insurance_expiry_date",
        "prequal_score",
    )
    present = [c for c in drop_order if c in existing]
    if not present:
        return

    with op.batch_alter_table(_TABLE) as batch:
        for col in present:
            batch.drop_column(col)
