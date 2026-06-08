# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Notifications — per-event-type channel preferences + digest queue (T9).

Wave 3 / T9 - every commercial construction ERP ships
hourly/daily digest emails and per-event-type channel routing (email vs in-app
vs Slack vs none). The ``notifications`` module had neither.

Schema deltas
-------------
Two new tables, both inspector-guarded:

``oe_notification_preference`` — per-user, per-event-type channel routing:
    * ``id``         String(36)  PK
    * ``user_id``    String(36)  FK→oe_users_user.id (CASCADE) — guarded
    * ``event_type`` String(80)  matches the event-bus dot-notation keys
                                 (``boq.position.created``, ``risk.simulated``)
    * ``channel``    String(32)  ``email|inapp|webhook|none``
    * ``enabled``    Boolean     default True
    * ``digest``     String(16)  ``realtime|hourly|daily`` (default ``realtime``)
    * Unique on ``(user_id, event_type, channel)``

``oe_notification_digest_queue`` — pending digest payloads:
    * ``id``            String(36)  PK
    * ``user_id``       String(36)  FK guarded
    * ``event_type``    String(80)
    * ``channel``       String(32)
    * ``payload``       JSON
    * ``scheduled_for`` DateTime    when the digest is due
    * ``sent_at``       DateTime    nullable
    * ``created_at``    DateTime    default now
    * Index on ``(scheduled_for, sent_at)``

Safety notes
------------
* Inspector-guarded — re-running on a partially migrated DB is a no-op.
* SQLite-safe — uses native ``create_table`` only.
* FK to ``oe_users_user`` is emitted only when that table exists at upgrade
  time (matches the v3082 / v3086 pattern).
* Reversible — ``downgrade()`` drops what ``upgrade()`` added.

Revision ID: v3090_notification_preferences
Revises: v3087_merge_wave2_heads
Created: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3090_notification_preferences"
down_revision: Union[str, Sequence[str], None] = "v3087_merge_wave2_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PREF_TABLE = "oe_notification_preference"
_QUEUE_TABLE = "oe_notification_digest_queue"
_USERS_TABLE = "oe_users_user"

_FK_PREF_USER = "fk_oe_notification_preference_user_id_users"
_FK_QUEUE_USER = "fk_oe_notification_digest_queue_user_id_users"
_UQ_PREF = "uq_oe_notification_preference_user_event_channel"
_IX_PREF_USER = "ix_oe_notification_preference_user_id"
_IX_QUEUE_SCHED = "ix_oe_notification_digest_queue_scheduled_for_sent_at"
_IX_QUEUE_USER = "ix_oe_notification_digest_queue_user_id"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


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

    users_present = _has_table(inspector, _USERS_TABLE)

    # ── 1. oe_notification_preference ────────────────────────────────────
    if not _has_table(inspector, _PREF_TABLE):
        if users_present:
            user_col = sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_USERS_TABLE}.id",
                    name=_FK_PREF_USER,
                    ondelete="CASCADE",
                ),
                nullable=False,
            )
        else:
            user_col = sa.Column(
                "user_id",
                sa.String(length=36),
                nullable=False,
            )

        op.create_table(
            _PREF_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            user_col,
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "digest",
                sa.String(length=16),
                nullable=False,
                server_default="realtime",
            ),
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
                "user_id",
                "event_type",
                "channel",
                name=_UQ_PREF,
            ),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, _PREF_TABLE) and not _has_index(inspector, _PREF_TABLE, _IX_PREF_USER):
        try:
            op.create_index(_IX_PREF_USER, _PREF_TABLE, ["user_id"])
        except Exception:  # noqa: BLE001 — idempotent guard
            pass

    # ── 2. oe_notification_digest_queue ──────────────────────────────────
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _QUEUE_TABLE):
        if users_present:
            user_col2 = sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_USERS_TABLE}.id",
                    name=_FK_QUEUE_USER,
                    ondelete="CASCADE",
                ),
                nullable=False,
            )
        else:
            user_col2 = sa.Column(
                "user_id",
                sa.String(length=36),
                nullable=False,
            )

        op.create_table(
            _QUEUE_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            user_col2,
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column(
                "payload",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "scheduled_for",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "sent_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, _QUEUE_TABLE) and not _has_index(inspector, _QUEUE_TABLE, _IX_QUEUE_SCHED):
        try:
            op.create_index(
                _IX_QUEUE_SCHED,
                _QUEUE_TABLE,
                ["scheduled_for", "sent_at"],
            )
        except Exception:  # noqa: BLE001
            pass
    if _has_table(inspector, _QUEUE_TABLE) and not _has_index(inspector, _QUEUE_TABLE, _IX_QUEUE_USER):
        try:
            op.create_index(_IX_QUEUE_USER, _QUEUE_TABLE, ["user_id"])
        except Exception:  # noqa: BLE001
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _QUEUE_TABLE, _IX_QUEUE_USER):
        op.drop_index(_IX_QUEUE_USER, table_name=_QUEUE_TABLE)
    if _has_index(inspector, _QUEUE_TABLE, _IX_QUEUE_SCHED):
        op.drop_index(_IX_QUEUE_SCHED, table_name=_QUEUE_TABLE)
    if _has_table(inspector, _QUEUE_TABLE):
        op.drop_table(_QUEUE_TABLE)

    inspector = sa.inspect(bind)
    if _has_index(inspector, _PREF_TABLE, _IX_PREF_USER):
        op.drop_index(_IX_PREF_USER, table_name=_PREF_TABLE)
    if _has_table(inspector, _PREF_TABLE):
        op.drop_table(_PREF_TABLE)
