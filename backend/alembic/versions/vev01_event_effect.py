# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""run-once ledger of event side effects: one row per (business event key, side effect)

Reshapes ``oe_event_effect`` (created by vdup9 with a unique ``key``): ``key`` becomes
``event_key``, ``effect`` widens to 120, ``event_name`` and ``record_id`` are added and
uniqueness moves to ``(event_key, effect)``, so an award drafts its purchase order or
contract exactly once even when the event is delivered twice at the same time. Each step
checks the live schema, so a database built from the models also passes.

Revision ID: vev01_event_effect
Revises: vpla13_plant_cost_board
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vev01_event_effect"
down_revision: str | Sequence[str] | None = "vpla13_plant_cost_board"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_event_effect"
_UQ = "uq_oe_event_effect_key_effect"
_OLD_IX = "ix_oe_event_effect_key"


def _state() -> tuple[set[str], set[str], set[str]]:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        return set(), set(), set()
    cols = {c["name"] for c in insp.get_columns(_TABLE)}
    idx = {i["name"] for i in insp.get_indexes(_TABLE)}
    uniq = {u["name"] for u in insp.get_unique_constraints(_TABLE)}
    return cols, idx, uniq


def upgrade() -> None:
    cols, idx, uniq = _state()
    if not cols:
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("event_key", sa.String(200), nullable=False),
            sa.Column("effect", sa.String(120), nullable=False, server_default=""),
            sa.Column("event_name", sa.String(200), nullable=True),
            sa.Column("record_id", sa.String(36), nullable=True),
            sa.UniqueConstraint("event_key", "effect", name=_UQ),
        )
        return
    if _OLD_IX in idx:
        op.drop_index(_OLD_IX, table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        if "key" in cols and "event_key" not in cols:
            batch.alter_column("key", new_column_name="event_key")
        batch.alter_column("effect", existing_type=sa.String(100), type_=sa.String(120), server_default="")
        if "event_name" not in cols:
            batch.add_column(sa.Column("event_name", sa.String(200), nullable=True))
        if "record_id" not in cols:
            batch.add_column(sa.Column("record_id", sa.String(36), nullable=True))
        if _UQ not in uniq:
            batch.create_unique_constraint(_UQ, ["event_key", "effect"])


def downgrade() -> None:
    cols, idx, uniq = _state()
    if not cols:
        return
    bind = op.get_bind()
    if "event_key" in cols:
        # the old shape allowed one claim per key: keep the first row of each key
        bind.execute(
            sa.text(
                f"DELETE FROM {_TABLE} WHERE id NOT IN "
                f"(SELECT min_id FROM (SELECT MIN(id) AS min_id FROM {_TABLE} GROUP BY event_key) AS keep)"
            )
        )
    with op.batch_alter_table(_TABLE) as batch:
        if _UQ in uniq:
            batch.drop_constraint(_UQ, type_="unique")
        if "record_id" in cols:
            batch.drop_column("record_id")
        if "event_name" in cols:
            batch.drop_column("event_name")
        batch.alter_column("effect", existing_type=sa.String(120), type_=sa.String(100), server_default="")
        if "event_key" in cols:
            batch.alter_column("event_key", new_column_name="key")
    if _OLD_IX not in idx:
        op.create_index(_OLD_IX, _TABLE, ["key"], unique=True)
