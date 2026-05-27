# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ERP-Chat — per-turn feedback + observability columns (T8 / Wave 3).

Autodesk AI Assist and Trimble's Construction One AI surface a thumbs
up/down on every assistant turn, plus an admin dashboard with token
spend, prompt-cache hit rate, and feedback-rate trend. Our ``erp_chat``
module persists messages but has neither — operators can't tell *why* a
chat answer was bad, and have no signal to tune prompts.

Schema deltas
-------------
On ``oe_erp_chat_message`` (only when columns are missing):
    * ``tokens_input``   Integer nullable — prompt tokens for the turn
    * ``tokens_output``  Integer nullable — completion tokens for the turn
    * ``cache_hit``      Boolean nullable — provider reported a prompt-cache hit
    * ``latency_ms``     Integer nullable — wall-clock LLM-call latency

New table ``oe_erp_chat_turn_feedback`` — one row per (message, user).
Re-submitting on the same message updates the rating in place
(``UNIQUE(message_id, user_id)``).

Safety notes
------------
* Inspector-guarded — re-running on a partially-migrated DB is a no-op.
* SQLite-safe — column adds use ``batch_alter_table``; ``create_table``
  is natively SQLite-safe.
* FKs to ``oe_erp_chat_message`` and ``oe_users_user`` are only emitted
  when those tables exist at upgrade time (same pattern as
  ``v3086_hse_osha_corrective_fsm`` and ``v3082_changeorders_approval_chain``).
* Reversible — ``downgrade()`` drops what ``upgrade()`` added, in reverse
  order.

Revision ID: v3089_erpchat_feedback
Revises: v3087_merge_wave2_heads
Created: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3089_erpchat_feedback"
down_revision: Union[str, Sequence[str], None] = "v3087_merge_wave2_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MESSAGE_TABLE = "oe_erp_chat_message"
_FEEDBACK_TABLE = "oe_erp_chat_turn_feedback"
_USERS_TABLE = "oe_users_user"

_FK_FB_MESSAGE = "fk_oe_erp_chat_turn_feedback_message_id_message"
_FK_FB_USER = "fk_oe_erp_chat_turn_feedback_user_id_users"
_IX_FB_MESSAGE = "ix_oe_erp_chat_turn_feedback_message_id"
_IX_FB_USER = "ix_oe_erp_chat_turn_feedback_user_id"
_UQ_FB_MSG_USER = "uq_oe_erp_chat_turn_feedback_message_user"


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

    # ── 1. Augment oe_erp_chat_message with observability columns ────────
    if _has_table(inspector, _MESSAGE_TABLE):
        needs = {
            "tokens_input": not _has_column(
                inspector,
                _MESSAGE_TABLE,
                "tokens_input",
            ),
            "tokens_output": not _has_column(
                inspector,
                _MESSAGE_TABLE,
                "tokens_output",
            ),
            "cache_hit": not _has_column(
                inspector,
                _MESSAGE_TABLE,
                "cache_hit",
            ),
            "latency_ms": not _has_column(
                inspector,
                _MESSAGE_TABLE,
                "latency_ms",
            ),
        }
        if any(needs.values()):
            with op.batch_alter_table(_MESSAGE_TABLE) as batch:
                if needs["tokens_input"]:
                    batch.add_column(sa.Column("tokens_input", sa.Integer(), nullable=True))
                if needs["tokens_output"]:
                    batch.add_column(sa.Column("tokens_output", sa.Integer(), nullable=True))
                if needs["cache_hit"]:
                    batch.add_column(sa.Column("cache_hit", sa.Boolean(), nullable=True))
                if needs["latency_ms"]:
                    batch.add_column(sa.Column("latency_ms", sa.Integer(), nullable=True))

    # ── 2. Create the per-turn feedback table ────────────────────────────
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _FEEDBACK_TABLE):
        message_present = _has_table(inspector, _MESSAGE_TABLE)
        users_present = _has_table(inspector, _USERS_TABLE)

        if message_present:
            message_col = sa.Column(
                "message_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_MESSAGE_TABLE}.id",
                    name=_FK_FB_MESSAGE,
                    ondelete="CASCADE",
                ),
                nullable=False,
            )
        else:
            # No FK if parent table isn't there yet — keeps the migration
            # idempotent on partially-bootstrapped installs. The model will
            # still enforce the relationship at the ORM level.
            message_col = sa.Column(
                "message_id",
                sa.String(length=36),
                nullable=False,
            )

        if users_present:
            user_col = sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_USERS_TABLE}.id",
                    name=_FK_FB_USER,
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        else:
            user_col = sa.Column(
                "user_id",
                sa.String(length=36),
                nullable=True,
            )

        op.create_table(
            _FEEDBACK_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            message_col,
            user_col,
            sa.Column(
                "rating",
                sa.Integer(),
                nullable=False,
            ),
            # Soft +1 / -1 constraint — SQLite CHECK is supported but we
            # also enforce it in the service. Skip on backends that don't
            # like inline CHECK in batch ops.
            sa.CheckConstraint(
                "rating IN (-1, 1)",
                name="ck_oe_erp_chat_turn_feedback_rating",
            ),
            sa.Column("comment", sa.Text(), nullable=True),
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
            sa.UniqueConstraint(
                "message_id",
                "user_id",
                name=_UQ_FB_MSG_USER,
            ),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, _FEEDBACK_TABLE) and not _has_index(inspector, _FEEDBACK_TABLE, _IX_FB_MESSAGE):
        try:
            op.create_index(
                _IX_FB_MESSAGE,
                _FEEDBACK_TABLE,
                ["message_id"],
            )
        except Exception:  # noqa: BLE001 — idempotent guard
            pass
    if _has_table(inspector, _FEEDBACK_TABLE) and not _has_index(inspector, _FEEDBACK_TABLE, _IX_FB_USER):
        try:
            op.create_index(_IX_FB_USER, _FEEDBACK_TABLE, ["user_id"])
        except Exception:  # noqa: BLE001
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _FEEDBACK_TABLE, _IX_FB_USER):
        op.drop_index(_IX_FB_USER, table_name=_FEEDBACK_TABLE)
    if _has_index(inspector, _FEEDBACK_TABLE, _IX_FB_MESSAGE):
        op.drop_index(_IX_FB_MESSAGE, table_name=_FEEDBACK_TABLE)
    if _has_table(inspector, _FEEDBACK_TABLE):
        op.drop_table(_FEEDBACK_TABLE)

    inspector = sa.inspect(bind)
    if _has_table(inspector, _MESSAGE_TABLE):
        drops: list[str] = []
        # Drop in reverse add order so SQLite batch rebuilds don't leave a
        # half-shaped table behind.
        for col in (
            "latency_ms",
            "cache_hit",
            "tokens_output",
            "tokens_input",
        ):
            if _has_column(inspector, _MESSAGE_TABLE, col):
                drops.append(col)
        if drops:
            with op.batch_alter_table(_MESSAGE_TABLE) as batch:
                for col in drops:
                    batch.drop_column(col)
