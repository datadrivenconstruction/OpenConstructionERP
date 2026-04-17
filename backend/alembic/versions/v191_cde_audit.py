"""v1.9.1 — CDE deep audit (RFC 33).

Three schema changes in one migration:

1. ``oe_cde_state_transition`` — new table, persistent audit log of every
   CDE state transition (Gate A/B/C). One row written inline by
   ``CDEService.transition_state`` for each valid transition.
2. ``oe_cde_revision.document_id`` — new String(36) column holding the
   cross-link into the Documents hub when a revision carries a file.
3. ``oe_transmittals_item.revision_id`` — new GUID column so a transmittal
   line item can point at a specific ``DocumentRevision`` (not just a
   generic Document).

Idempotent: inspects the live schema first and skips already-present
columns/tables. Safe to re-run against a SQLite dev DB where
``Base.metadata.create_all`` might have created the new objects already.

Revision ID: v191_cde_audit
Revises: v191_meetings_document_ids
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v191_cde_audit"
down_revision: Union[str, None] = "v191_dwg_entity_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Helpers ──────────────────────────────────────────────────────────────


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def _has_index(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


# ── Upgrade ──────────────────────────────────────────────────────────────


def upgrade() -> None:
    # 1. oe_cde_state_transition — audit log.
    if not _table_exists("oe_cde_state_transition"):
        op.create_table(
            "oe_cde_state_transition",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "container_id",
                sa.String(36),
                sa.ForeignKey("oe_cde_container.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("from_state", sa.String(50), nullable=False),
            sa.Column("to_state", sa.String(50), nullable=False),
            sa.Column("gate_code", sa.String(10), nullable=True),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("user_role", sa.String(50), nullable=True),
            sa.Column("reason", sa.Text, nullable=True),
            sa.Column("signature", sa.String(200), nullable=True),
            sa.Column(
                "transitioned_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    # Safety index — index the FK column even on dialects that don't create
    # an index automatically for FK constraints (SQLite).
    if _table_exists("oe_cde_state_transition") and not _has_index(
        "oe_cde_state_transition", "ix_oe_cde_state_transition_container_id"
    ):
        try:
            op.create_index(
                "ix_oe_cde_state_transition_container_id",
                "oe_cde_state_transition",
                ["container_id"],
            )
        except Exception:
            # Some backends auto-create this; swallow the duplicate error.
            pass

    # 2. oe_cde_revision.document_id — cross-link column.
    if _table_exists("oe_cde_revision") and not _has_column(
        "oe_cde_revision", "document_id"
    ):
        op.add_column(
            "oe_cde_revision",
            sa.Column("document_id", sa.String(36), nullable=True),
        )
        if not _has_index("oe_cde_revision", "ix_oe_cde_revision_document_id"):
            try:
                op.create_index(
                    "ix_oe_cde_revision_document_id",
                    "oe_cde_revision",
                    ["document_id"],
                )
            except Exception:
                pass

    # 3. oe_transmittals_item.revision_id — CDE revision link.
    if _table_exists("oe_transmittals_item") and not _has_column(
        "oe_transmittals_item", "revision_id"
    ):
        op.add_column(
            "oe_transmittals_item",
            sa.Column("revision_id", sa.String(36), nullable=True),
        )
        if not _has_index(
            "oe_transmittals_item", "ix_oe_transmittals_item_revision_id"
        ):
            try:
                op.create_index(
                    "ix_oe_transmittals_item_revision_id",
                    "oe_transmittals_item",
                    ["revision_id"],
                )
            except Exception:
                pass


# ── Downgrade ────────────────────────────────────────────────────────────


def downgrade() -> None:
    # 3. Revert oe_transmittals_item.revision_id.
    if _has_column("oe_transmittals_item", "revision_id"):
        try:
            op.drop_index(
                "ix_oe_transmittals_item_revision_id",
                table_name="oe_transmittals_item",
            )
        except Exception:
            pass
        with op.batch_alter_table("oe_transmittals_item") as batch:
            batch.drop_column("revision_id")

    # 2. Revert oe_cde_revision.document_id.
    if _has_column("oe_cde_revision", "document_id"):
        try:
            op.drop_index(
                "ix_oe_cde_revision_document_id",
                table_name="oe_cde_revision",
            )
        except Exception:
            pass
        with op.batch_alter_table("oe_cde_revision") as batch:
            batch.drop_column("document_id")

    # 1. Drop the state-transition audit log.
    if _table_exists("oe_cde_state_transition"):
        try:
            op.drop_index(
                "ix_oe_cde_state_transition_container_id",
                table_name="oe_cde_state_transition",
            )
        except Exception:
            pass
        op.drop_table("oe_cde_state_transition")
