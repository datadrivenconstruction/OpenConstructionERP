# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Meetings — Newforma-style recurring series + attendance check-in.

Newforma Project Meetings and Procore Meetings both ship a *recurring
series* model — a single "master" meeting carries an iCal-style RRULE
(``FREQ=WEEKLY;BYDAY=MO;COUNT=12``) and the system materialises future
occurrences from it.  Both products also ship *attendance check-in*
with optional signature capture for verified records (Newforma's
"Meeting Attendance" workflow + Procore's Mobile Check-In).

Our ``meetings`` module is currently flat one-off events.  This
migration adds the schema underpinnings to lift that limitation:

Schema deltas
-------------
On ``oe_meetings_meeting`` (only when columns are missing):
    * ``series_id``         GUID(36) nullable — master meeting's id, or
                            NULL for non-recurring one-off meetings.
                            The master meeting also stamps its own id
                            here so a single ``WHERE series_id = ?``
                            scoops master + all occurrences.
    * ``recurrence_rule``   String(200) nullable — RFC 5545 RRULE
                            (only populated on the series master).
    * ``is_series_master``  Boolean default False.

Index ``ix_oe_meetings_meeting_series_id`` on ``series_id`` so
"fetch the whole series" stays O(log n).

New table ``oe_meetings_attendance`` (only when missing) — per-meeting
attendance records that can carry a signature image path.  Distinct
from the JSON ``attendees`` array already on Meeting because:
    * check-in is a *transactional* event (timestamped),
    * signatures are blobs on disk and need their own row,
    * non-system users (external_name only, no user_id) must be
      representable without polluting ``oe_users_user``.

Unique constraint on ``(meeting_id, user_id)`` so a single user can't
be double-checked-in.  External attendees (NULL user_id) are not
subject to that constraint — multiple "John Doe" walk-ins are fine.

Safety notes
------------
* Inspector-guarded — re-running on a partially-migrated DB is a no-op.
* SQLite-safe — column adds use ``batch_alter_table``; ``create_table``
  is natively SQLite-safe.
* FK to ``oe_users_user`` only emitted when that table exists at
  upgrade time (same pattern as ``v3086_hse_osha_corrective_fsm`` and
  ``v3082_changeorders_approval_chain``).
* Reversible — ``downgrade()`` drops what ``upgrade()`` added.

Revision ID: v3088_meetings_recurring_attendance
Revises: v3087_merge_wave2_heads
Created: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3088_meetings_recurring_attendance"
down_revision: Union[str, Sequence[str], None] = "v3087_merge_wave2_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MEETING_TABLE = "oe_meetings_meeting"
_ATTENDANCE_TABLE = "oe_meetings_attendance"
_USERS_TABLE = "oe_users_user"

_IX_MEETING_SERIES = "ix_oe_meetings_meeting_series_id"
_IX_ATTENDANCE_MEETING = "ix_oe_meetings_attendance_meeting_id"
_UQ_ATTENDANCE_MEETING_USER = "uq_oe_meetings_attendance_meeting_user"
_FK_ATTENDANCE_MEETING = "fk_oe_meetings_attendance_meeting_id_meeting"
_FK_ATTENDANCE_USER = "fk_oe_meetings_attendance_user_id_users"


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


def _has_unique(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    try:
        return any(uc.get("name") == name for uc in inspector.get_unique_constraints(table))
    except NotImplementedError:  # pragma: no cover — backend without UC reflection
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. Augment oe_meetings_meeting with recurrence columns ────────────
    if _has_table(inspector, _MEETING_TABLE):
        needs = {
            "series_id": not _has_column(inspector, _MEETING_TABLE, "series_id"),
            "recurrence_rule": not _has_column(
                inspector,
                _MEETING_TABLE,
                "recurrence_rule",
            ),
            "is_series_master": not _has_column(
                inspector,
                _MEETING_TABLE,
                "is_series_master",
            ),
        }
        if any(needs.values()):
            with op.batch_alter_table(_MEETING_TABLE) as batch:
                if needs["series_id"]:
                    batch.add_column(sa.Column("series_id", sa.String(length=36), nullable=True))
                if needs["recurrence_rule"]:
                    batch.add_column(
                        sa.Column(
                            "recurrence_rule",
                            sa.String(length=200),
                            nullable=True,
                        )
                    )
                if needs["is_series_master"]:
                    batch.add_column(
                        sa.Column(
                            "is_series_master",
                            sa.Boolean(),
                            nullable=False,
                            server_default=sa.false(),
                        )
                    )

        # Re-inspect because batch_alter_table on SQLite re-creates the table.
        inspector = sa.inspect(bind)
        if _has_column(inspector, _MEETING_TABLE, "series_id") and not _has_index(
            inspector, _MEETING_TABLE, _IX_MEETING_SERIES
        ):
            try:
                op.create_index(
                    _IX_MEETING_SERIES,
                    _MEETING_TABLE,
                    ["series_id"],
                )
            except Exception:  # noqa: BLE001 — idempotent guard
                pass

    # ── 2. Create the attendance table ────────────────────────────────────
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _ATTENDANCE_TABLE):
        users_present = _has_table(inspector, _USERS_TABLE)
        meeting_present = _has_table(inspector, _MEETING_TABLE)

        if meeting_present:
            meeting_col = sa.Column(
                "meeting_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_MEETING_TABLE}.id",
                    name=_FK_ATTENDANCE_MEETING,
                    ondelete="CASCADE",
                ),
                nullable=False,
            )
        else:
            meeting_col = sa.Column(
                "meeting_id",
                sa.String(length=36),
                nullable=False,
            )

        if users_present:
            user_col = sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_USERS_TABLE}.id",
                    name=_FK_ATTENDANCE_USER,
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
            _ATTENDANCE_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            meeting_col,
            user_col,
            sa.Column("external_name", sa.String(length=200), nullable=True),
            sa.Column(
                "checked_in_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "signature_image_path",
                sa.String(length=500),
                nullable=True,
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
            # NB: Unique on (meeting_id, user_id) protects against duplicate
            # user check-ins. SQLite treats NULL as distinct, so external
            # attendees (NULL user_id) can have multiple rows — exactly what
            # we want for walk-ins where two "John Doe" entries are legit.
            sa.UniqueConstraint(
                "meeting_id",
                "user_id",
                name=_UQ_ATTENDANCE_MEETING_USER,
            ),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, _ATTENDANCE_TABLE) and not _has_index(
        inspector, _ATTENDANCE_TABLE, _IX_ATTENDANCE_MEETING
    ):
        try:
            op.create_index(
                _IX_ATTENDANCE_MEETING,
                _ATTENDANCE_TABLE,
                ["meeting_id"],
            )
        except Exception:  # noqa: BLE001
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop attendance table first (FK -> meeting; CASCADE on the FK means
    # nothing on the meetings side cares).
    if _has_index(inspector, _ATTENDANCE_TABLE, _IX_ATTENDANCE_MEETING):
        op.drop_index(_IX_ATTENDANCE_MEETING, table_name=_ATTENDANCE_TABLE)
    if _has_table(inspector, _ATTENDANCE_TABLE):
        op.drop_table(_ATTENDANCE_TABLE)

    inspector = sa.inspect(bind)
    if _has_index(inspector, _MEETING_TABLE, _IX_MEETING_SERIES):
        op.drop_index(_IX_MEETING_SERIES, table_name=_MEETING_TABLE)

    if _has_table(inspector, _MEETING_TABLE):
        drops: list[str] = []
        for col in ("is_series_master", "recurrence_rule", "series_id"):
            if _has_column(inspector, _MEETING_TABLE, col):
                drops.append(col)
        if drops:
            with op.batch_alter_table(_MEETING_TABLE) as batch:
                for col in drops:
                    batch.drop_column(col)
