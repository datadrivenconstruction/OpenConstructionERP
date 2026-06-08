# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Change-orders multi-step approval chain + commitment / RFI links.

Construction management platform style change management routes a CO
through an ordered list of approvers. Each step records the assigned approver, their decision
(``pending``/``approved``/``rejected``), an optional comment, and the
timestamp of the decision. The CO header carries the cursor pointing at
the *currently active* step plus JSON arrays linking the CO to its
originating commitments / POs and RFIs.

Schema deltas
-------------
New table ``oe_changeorder_approval`` (ordered approver steps).
Added columns on ``oe_changeorders_order``:
    * ``linked_po_ids``           JSON, default ``'[]'``
    * ``linked_rfi_ids``          JSON, default ``'[]'``
    * ``current_approval_step``   Integer, nullable
    + index ``ix_oe_changeorders_order_current_approval_step`` so the
      "pending my approval" board can scan the cursor cheaply.

Safety notes
------------
* Inspector-guarded. Re-running on a partially-migrated DB is a no-op.
* SQLite-safe: column adds + index creation are batched.
* The FK from the new table to ``oe_users_user`` is **only** emitted when
  that table exists at upgrade time. On a partial SQLite state where
  users-module migrations haven't landed yet we fall back to a plain
  column so the upgrade still completes (we've been bitten by this
  before — see ``v2918_risk_owner_user_id`` for the same guard).

Revision ID: v3082_changeorders_approval_chain
Revises: v3071_merge_clash_and_files
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3082_changeorders_approval_chain"
down_revision: Union[str, Sequence[str], None] = "v3071_merge_clash_and_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CO_TABLE = "oe_changeorders_order"
_APPROVAL_TABLE = "oe_changeorder_approval"
_USERS_TABLE = "oe_users_user"

_FK_APPROVER = "fk_oe_changeorder_approval_approver_user_id_users"
_FK_CO = "fk_oe_changeorder_approval_change_order_id_changeorder"
_IX_CURSOR = "ix_oe_changeorders_order_current_approval_step"
_IX_APPROVAL_CO = "ix_oe_changeorder_approval_change_order_id"
_IX_APPROVAL_APPROVER = "ix_oe_changeorder_approval_approver_user_id"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(col["name"] == name for col in inspector.get_columns(table))


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. Create the approval-chain table (if missing) ──────────────────
    if not _has_table(inspector, _APPROVAL_TABLE):
        # FK to users only if the users table exists. On a partial SQLite
        # state without it, fall back to a plain column so the migration
        # still completes; the runtime service treats unknown approvers
        # as missing rather than crashing.
        users_present = _has_table(inspector, _USERS_TABLE)
        approver_col: sa.Column
        if users_present:
            approver_col = sa.Column(
                "approver_user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_USERS_TABLE}.id",
                    name=_FK_APPROVER,
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        else:
            approver_col = sa.Column(
                "approver_user_id",
                sa.String(length=36),
                nullable=True,
            )

        op.create_table(
            _APPROVAL_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "change_order_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_CO_TABLE}.id",
                    name=_FK_CO,
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("step_order", sa.Integer(), nullable=False),
            approver_col,
            sa.Column(
                "decision",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "decided_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("comments", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "change_order_id",
                "step_order",
                name="uq_oe_changeorder_approval_change_order_id_step_order",
            ),
        )

    # Indexes on the approval table (idempotent).
    if not _has_index(inspector, _APPROVAL_TABLE, _IX_APPROVAL_CO):
        try:
            op.create_index(
                _IX_APPROVAL_CO,
                _APPROVAL_TABLE,
                ["change_order_id"],
            )
        except Exception:  # noqa: BLE001 — idempotent guard
            pass

    if not _has_index(inspector, _APPROVAL_TABLE, _IX_APPROVAL_APPROVER):
        try:
            op.create_index(
                _IX_APPROVAL_APPROVER,
                _APPROVAL_TABLE,
                ["approver_user_id", "decision"],
            )
        except Exception:  # noqa: BLE001
            pass

    # ── 2. Add columns to the change-order header ────────────────────────
    if _has_table(inspector, _CO_TABLE):
        needs_linked_po = not _has_column(inspector, _CO_TABLE, "linked_po_ids")
        needs_linked_rfi = not _has_column(inspector, _CO_TABLE, "linked_rfi_ids")
        needs_cursor = not _has_column(inspector, _CO_TABLE, "current_approval_step")
        if needs_linked_po or needs_linked_rfi or needs_cursor:
            with op.batch_alter_table(_CO_TABLE) as batch:
                if needs_linked_po:
                    batch.add_column(
                        sa.Column(
                            "linked_po_ids",
                            sa.JSON(),
                            nullable=True,
                            server_default="[]",
                        )
                    )
                if needs_linked_rfi:
                    batch.add_column(
                        sa.Column(
                            "linked_rfi_ids",
                            sa.JSON(),
                            nullable=True,
                            server_default="[]",
                        )
                    )
                if needs_cursor:
                    batch.add_column(
                        sa.Column(
                            "current_approval_step",
                            sa.Integer(),
                            nullable=True,
                        )
                    )

    # Re-inspect because batch_alter_table on SQLite re-creates the table.
    inspector = sa.inspect(bind)
    if _has_column(inspector, _CO_TABLE, "current_approval_step") and not _has_index(inspector, _CO_TABLE, _IX_CURSOR):
        try:
            op.create_index(_IX_CURSOR, _CO_TABLE, ["current_approval_step"])
        except Exception:  # noqa: BLE001
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop the approval index/table first (FK cascade points back at CO).
    if _has_index(inspector, _APPROVAL_TABLE, _IX_APPROVAL_APPROVER):
        op.drop_index(_IX_APPROVAL_APPROVER, table_name=_APPROVAL_TABLE)
    if _has_index(inspector, _APPROVAL_TABLE, _IX_APPROVAL_CO):
        op.drop_index(_IX_APPROVAL_CO, table_name=_APPROVAL_TABLE)
    if _has_table(inspector, _APPROVAL_TABLE):
        op.drop_table(_APPROVAL_TABLE)

    # Re-inspect after the drop so the index lookup uses fresh metadata.
    inspector = sa.inspect(bind)
    if _has_index(inspector, _CO_TABLE, _IX_CURSOR):
        op.drop_index(_IX_CURSOR, table_name=_CO_TABLE)

    if _has_table(inspector, _CO_TABLE):
        drops: list[str] = []
        if _has_column(inspector, _CO_TABLE, "current_approval_step"):
            drops.append("current_approval_step")
        if _has_column(inspector, _CO_TABLE, "linked_rfi_ids"):
            drops.append("linked_rfi_ids")
        if _has_column(inspector, _CO_TABLE, "linked_po_ids"):
            drops.append("linked_po_ids")
        if drops:
            with op.batch_alter_table(_CO_TABLE) as batch:
                for col in drops:
                    batch.drop_column(col)
