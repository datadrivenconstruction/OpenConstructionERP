# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""round3_fk_indexes — top FK-column indexes for v4.3 round-3 sweep.

Strictly-additive sweep that backfills missing covering indexes on FK
columns flagged by the v4.3 DB-integrity audit. Every column targeted
here is an existing FK (or FK-like join key) that the ORM did not flag
``index=True`` on at table-creation time, leading to seq-scans on the
parent → child join path.

Targets (table.column → idx_<table>_<column>) — only columns that did
NOT already have a covering index were retained from the audit list:

* ``oe_contracts_progress_claim_line.contract_line_id``
* ``oe_clash_issue.first_seen_run_id``
* ``oe_clash_issue.last_seen_run_id``
* ``oe_clash_issue.resolved_run_id``
* ``oe_crm_opportunity.lost_reason_code``  (audit row ``win_loss_reason_code`` —
  actual column name is ``lost_reason_code``)
* ``oe_equipment_work_order.schedule_id``

The audit also listed the following but they were already indexed at
model-definition time (verified by reading ``models.py``) — skipped:

* ``oe_contracts_progress_claim.contract_id``        (``index=True``)
* ``oe_contracts_contract_line.contract_id``         (``index=True``)
* ``oe_contracts_final_account.contract_id``         (UniqueConstraint)
* ``oe_meetings_attendance.meeting_id``              (explicit Index)
* ``oe_match_elements_search_log.session_id``        (explicit Index)
* ``oe_notification_preference.user_id``             (explicit Index)
* ``oe_notification_digest_queue.user_id``           (explicit Index)
* ``oe_crm_activity.stage_id``                       (column does not exist;
  ``stage_id`` only lives on ``oe_crm_opportunity``)

Idempotent — inspector-guarded so re-runs on a partially-migrated DB
skip indexes that already exist. SQLite-safe (op.create_index is
cross-dialect; no PG-only DDL).

Revision ID: v3096
Revises: v41_coordination_thresholds
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3096"
down_revision: Union[str, Sequence[str], None] = "v41_coordination_thresholds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, index_name) tuples. Index name follows
# ``ix_<table>_<column>`` per the project's existing convention.
_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "oe_contracts_progress_claim_line",
        "contract_line_id",
        "ix_oe_contracts_progress_claim_line_contract_line_id",
    ),
    (
        "oe_clash_issue",
        "first_seen_run_id",
        "ix_oe_clash_issue_first_seen_run_id",
    ),
    (
        "oe_clash_issue",
        "last_seen_run_id",
        "ix_oe_clash_issue_last_seen_run_id",
    ),
    (
        "oe_clash_issue",
        "resolved_run_id",
        "ix_oe_clash_issue_resolved_run_id",
    ),
    (
        "oe_crm_opportunity",
        "lost_reason_code",
        "ix_oe_crm_opportunity_lost_reason_code",
    ),
    (
        "oe_equipment_work_order",
        "schedule_id",
        "ix_oe_equipment_work_order_schedule_id",
    ),
)


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    """Return the set of existing index names for ``table``, or empty
    set if the table itself is missing (defensive — partial migrations).
    """
    if table not in inspector.get_table_names():
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def _table_columns(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    """Return the set of column names on ``table``, or empty set if the
    table is missing. Guards against column-rename divergence.
    """
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    """Create each FK-column index if (and only if) it is missing."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, column, ix_name in _INDEXES:
        cols = _table_columns(inspector, table)
        if column not in cols:
            # Column rename / table missing on this DB — skip rather than
            # crash a partially-migrated environment.
            continue
        existing = _existing_index_names(inspector, table)
        if ix_name in existing:
            continue
        try:
            op.create_index(ix_name, table, [column])
        except sa.exc.OperationalError:
            # Race / dialect-specific "already exists" — keep migration
            # idempotent across SQLite + Postgres.
            pass


def downgrade() -> None:
    """Drop each FK-column index if present."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, _column, ix_name in _INDEXES:
        existing = _existing_index_names(inspector, table)
        if ix_name not in existing:
            continue
        try:
            op.drop_index(ix_name, table_name=table)
        except sa.exc.OperationalError:
            pass
