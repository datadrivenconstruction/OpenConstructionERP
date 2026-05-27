# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Service module: SLA-timer columns + recurring-schedule table.

Wave 3 / T10 — brings the ``oe_service`` module to ServiceTitan / FieldEdge
feature parity for the two field-ops gaps still open after Wave 2:

* SLA breach timing: the existing ``sla_due_at`` (string-typed ISO) already
  records the deadline, but we add a dedicated ``sla_breached_at`` column so
  the dashboard can distinguish "still ticking" from "breach already
  recorded" without re-parsing every ticket's ISO timestamp on every poll.
* Recurring maintenance contracts: ServiceTitan-style RRULE-driven schedules
  that materialise tickets automatically. The existing ``oe_service_schedule``
  is asset-scoped PPM (next_due_date + frequency); this new
  ``oe_service_recurring_schedule`` is project-scoped, RRULE-driven, and
  materialises full templated tickets — a strictly additive table.

Idempotent — inspector-guarded so re-runs on a partially-migrated DB skip
columns/tables already present. SQLite-safe (GUID() ⇒ VARCHAR(36)).

Revision ID: v3091_service_sla_recurring
Revises: v3087_merge_wave2_heads
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3091_service_sla_recurring"
down_revision: Union[str, Sequence[str], None] = "v3087_merge_wave2_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TICKET_TABLE = "oe_service_ticket"
_SCHEDULE_TABLE = "oe_service_recurring_schedule"


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
    """Add SLA-timer columns + create recurring-schedule table."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    # ── oe_service_ticket: additive columns ──────────────────────────────
    #
    # ``priority`` already exists from v3010 (NOT NULL, default 'med'); we do
    # NOT re-add it here even though the spec mentions it — re-adding a NOT
    # NULL column on a populated table is a footgun for SQLite ALTER and the
    # column is already wired through schemas + service layer.
    ticket_cols = _existing_cols(inspector, _TICKET_TABLE)

    if _has_table(inspector, _TICKET_TABLE):
        # ``sla_due_at`` already lives in v3010 as String(40) (ISO timestamp).
        # We keep that representation — adding a new DateTime column would
        # split the source of truth. The new piece is ``sla_breached_at``.
        if "sla_breached_at" not in ticket_cols:
            op.add_column(
                _TICKET_TABLE,
                sa.Column("sla_breached_at", sa.String(length=40), nullable=True),
            )

        if "recurring_schedule_id" not in ticket_cols:
            op.add_column(
                _TICKET_TABLE,
                sa.Column("recurring_schedule_id", guid_type, nullable=True),
            )
            # Index so the recurring-schedule list view can pull child tickets
            # cheaply without a full table scan.
            existing = _existing_index_names(inspector, _TICKET_TABLE)
            if "ix_oe_service_ticket_recurring_schedule_id" not in existing:
                try:
                    op.create_index(
                        "ix_oe_service_ticket_recurring_schedule_id",
                        _TICKET_TABLE,
                        ["recurring_schedule_id"],
                    )
                except sa.exc.OperationalError:
                    pass

    # ── oe_service_recurring_schedule: new table ─────────────────────────
    if not _has_table(inspector, _SCHEDULE_TABLE):
        op.create_table(
            _SCHEDULE_TABLE,
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
            sa.Column("project_id", guid_type, nullable=True, index=True),
            sa.Column("contract_id", guid_type, nullable=True, index=True),
            sa.Column("name", sa.String(200), nullable=False),
            # RRULE (RFC 5545): e.g. "FREQ=MONTHLY;BYMONTHDAY=1".
            sa.Column("rrule", sa.String(200), nullable=False),
            # Full ServiceTicket-shaped payload used as the template for each
            # materialised occurrence. Stored as JSON so non-ticket fields
            # (e.g. checklist links, recipient hints) can ride along.
            sa.Column(
                "template_ticket_data",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            # Both timestamps stored as ISO strings to match the
            # existing service-module string-typed datetime convention.
            sa.Column("next_run_at", sa.String(length=40), nullable=True),
            sa.Column("last_run_at", sa.String(length=40), nullable=True),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

        # next_run_at index — the cron worker scans for `enabled & next_run_at < now`.
        existing = _existing_index_names(inspector, _SCHEDULE_TABLE)
        if "ix_oe_service_recurring_schedule_next_run_at" not in existing:
            try:
                op.create_index(
                    "ix_oe_service_recurring_schedule_next_run_at",
                    _SCHEDULE_TABLE,
                    ["next_run_at"],
                )
            except sa.exc.OperationalError:
                pass
        if "ix_oe_service_recurring_schedule_enabled" not in existing:
            try:
                op.create_index(
                    "ix_oe_service_recurring_schedule_enabled",
                    _SCHEDULE_TABLE,
                    ["enabled"],
                )
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    """Drop the recurring-schedule table and remove SLA-timer columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _SCHEDULE_TABLE):
        existing = _existing_index_names(inspector, _SCHEDULE_TABLE)
        for ix in (
            "ix_oe_service_recurring_schedule_next_run_at",
            "ix_oe_service_recurring_schedule_enabled",
        ):
            if ix in existing:
                try:
                    op.drop_index(ix, table_name=_SCHEDULE_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_SCHEDULE_TABLE)

    ticket_cols = _existing_cols(inspector, _TICKET_TABLE)
    ticket_idx = _existing_index_names(inspector, _TICKET_TABLE)
    if "ix_oe_service_ticket_recurring_schedule_id" in ticket_idx:
        try:
            op.drop_index(
                "ix_oe_service_ticket_recurring_schedule_id",
                table_name=_TICKET_TABLE,
            )
        except sa.exc.OperationalError:
            pass
    if "recurring_schedule_id" in ticket_cols:
        op.drop_column(_TICKET_TABLE, "recurring_schedule_id")
    if "sla_breached_at" in ticket_cols:
        op.drop_column(_TICKET_TABLE, "sla_breached_at")
