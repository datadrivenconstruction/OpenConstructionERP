# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering: integrated 5D estimating suite style bid leveling + addendum tracking.

Closes the gap with construction CDE platform tendering and integrated 5D
estimating suite tendering by introducing two first-class tendering concepts
our module lacked:

* **Addenda** — mid-tender clarifications/revisions every bidder must
  acknowledge. A new ``oe_tender_addendum`` table holds the revision
  history (revision_no auto-increments per package), publication
  timestamps, and a JSON list of bidder acknowledgements.
* **Bid leveling** — normalize competing bids onto the package's
  reference BOQ so the comparison reflects *price* differences, not
  *quote* differences. Two new columns are added to ``oe_tendering_bid``:
    - ``leveled_amount``   Numeric(18,2), nullable
    - ``leveling_notes``   Text, nullable (JSON-encoded per-line log)

Safety notes
------------
* Inspector-guarded. Re-running on a partially-migrated DB is a no-op.
* SQLite-safe: column adds use ``batch_alter_table``.
* FK to ``oe_users_user`` is **only** emitted when that table exists at
  upgrade time. On a partial SQLite state without it we fall back to a
  plain column. Same guard pattern as ``v3082_changeorders_approval_chain``.

Revision ID: v3085_tendering_addendum_leveling
Revises: v3083_merge_v311_heads
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3085_tendering_addendum_leveling"
down_revision: Union[str, Sequence[str], None] = "v3083_merge_v311_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ADDENDUM_TABLE = "oe_tender_addendum"
_PACKAGE_TABLE = "oe_tendering_package"
_BID_TABLE = "oe_tendering_bid"
_USERS_TABLE = "oe_users_user"

_FK_PACKAGE = "fk_oe_tender_addendum_package_id_tendering_package"
_FK_PUBLISHER = "fk_oe_tender_addendum_published_by_user_id_users"
_UQ_PACKAGE_REV = "uq_oe_tender_addendum_package_id_revision_no"
_IX_PACKAGE = "ix_oe_tender_addendum_package_id"


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

    # ── 1. Create the addendum table (if missing) ────────────────────────
    if not _has_table(inspector, _ADDENDUM_TABLE):
        users_present = _has_table(inspector, _USERS_TABLE)
        if users_present:
            publisher_col = sa.Column(
                "published_by_user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_USERS_TABLE}.id",
                    name=_FK_PUBLISHER,
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        else:
            publisher_col = sa.Column(
                "published_by_user_id",
                sa.String(length=36),
                nullable=True,
            )

        op.create_table(
            _ADDENDUM_TABLE,
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
                "package_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_PACKAGE_TABLE}.id",
                    name=_FK_PACKAGE,
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("revision_no", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column(
                "published_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            publisher_col,
            sa.Column(
                "acknowledged_by",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.UniqueConstraint(
                "package_id",
                "revision_no",
                name=_UQ_PACKAGE_REV,
            ),
        )

    if not _has_index(inspector, _ADDENDUM_TABLE, _IX_PACKAGE):
        try:
            op.create_index(
                _IX_PACKAGE,
                _ADDENDUM_TABLE,
                ["package_id"],
            )
        except Exception:  # noqa: BLE001 — idempotent guard
            pass

    # ── 2. Add leveling columns to the bid table ─────────────────────────
    if _has_table(inspector, _BID_TABLE):
        needs_leveled_amount = not _has_column(inspector, _BID_TABLE, "leveled_amount")
        needs_leveling_notes = not _has_column(inspector, _BID_TABLE, "leveling_notes")
        if needs_leveled_amount or needs_leveling_notes:
            with op.batch_alter_table(_BID_TABLE) as batch:
                if needs_leveled_amount:
                    batch.add_column(
                        sa.Column(
                            "leveled_amount",
                            sa.Numeric(18, 2),
                            nullable=True,
                        )
                    )
                if needs_leveling_notes:
                    batch.add_column(
                        sa.Column(
                            "leveling_notes",
                            sa.Text(),
                            nullable=True,
                        )
                    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop the addendum index/table first.
    if _has_index(inspector, _ADDENDUM_TABLE, _IX_PACKAGE):
        op.drop_index(_IX_PACKAGE, table_name=_ADDENDUM_TABLE)
    if _has_table(inspector, _ADDENDUM_TABLE):
        op.drop_table(_ADDENDUM_TABLE)

    # Re-inspect after the drop so the column lookup uses fresh metadata.
    inspector = sa.inspect(bind)
    if _has_table(inspector, _BID_TABLE):
        drops: list[str] = []
        if _has_column(inspector, _BID_TABLE, "leveling_notes"):
            drops.append("leveling_notes")
        if _has_column(inspector, _BID_TABLE, "leveled_amount"):
            drops.append("leveled_amount")
        if drops:
            with op.batch_alter_table(_BID_TABLE) as batch:
                for col in drops:
                    batch.drop_column(col)
