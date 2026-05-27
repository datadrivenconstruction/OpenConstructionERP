# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE — OSHA 300 recordable columns + standalone CorrectiveAction FSM table.

Sphera SafetyStratus and Procore Quality & Safety ship a full OSHA Form 300
incident log export plus a corrective-action workflow with a formal
verification step. Our ``hse_advanced`` module already carries the bulk of
the workflow (CAPA, audits, investigations, KPIs) but is missing the
OSHA-recordable bookkeeping on ``oe_safety_incident`` and a lightweight
*incident → corrective action* table with a strict
``pending → in_progress → verified → closed`` FSM.

Schema deltas
-------------
On ``oe_safety_incident`` (only when columns are missing):
    * ``osha_recordable``   Boolean default False
    * ``osha_case_number``  String(32) nullable
    * ``days_away``         Integer nullable
    * ``days_restricted``   Integer nullable
    * ``root_cause_method`` String(32) nullable
        (``5_whys`` / ``fishbone`` / ``tap_root`` / ``other``)
    * ``root_cause_tags``   JSON default ``'[]'``

New table ``oe_hse_corrective_action`` (only when missing) — a slim
incident-scoped corrective-action record distinct from the broader
``oe_hse_advanced_capa`` (audit/JSA/observation-scoped CAPA). The FSM is
intentionally simpler: pending → in_progress → verified → closed.

Safety notes
------------
* Inspector-guarded — re-running on a partially-migrated DB is a no-op.
* SQLite-safe — column adds use ``batch_alter_table``; ``create_table`` is
  natively SQLite-safe.
* FK to ``oe_users_user`` is only emitted when that table exists at
  upgrade time (same pattern as ``v3082_changeorders_approval_chain`` and
  ``v2918_risk_owner_user_id``).
* Reversible — ``downgrade()`` drops what ``upgrade()`` added, in reverse
  order.

Revision ID: v3086_hse_osha_corrective_fsm
Revises: v3083_merge_v311_heads
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3086_hse_osha_corrective_fsm"
down_revision: Union[str, Sequence[str], None] = "v3083_merge_v311_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INCIDENT_TABLE = "oe_safety_incident"
_CA_TABLE = "oe_hse_corrective_action"
_USERS_TABLE = "oe_users_user"

_FK_CA_ASSIGNED = "fk_oe_hse_corrective_action_assigned_to_user_id_users"
_FK_CA_VERIFIED = "fk_oe_hse_corrective_action_verified_by_user_id_users"
_IX_CA_INCIDENT = "ix_oe_hse_corrective_action_incident_id"
_IX_CA_STATUS = "ix_oe_hse_corrective_action_status"
_IX_INCIDENT_RECORDABLE = "ix_oe_safety_incident_osha_recordable"


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

    # ── 1. Augment oe_safety_incident with OSHA-recordable columns ──────
    if _has_table(inspector, _INCIDENT_TABLE):
        needs = {
            "osha_recordable": not _has_column(
                inspector,
                _INCIDENT_TABLE,
                "osha_recordable",
            ),
            "osha_case_number": not _has_column(
                inspector,
                _INCIDENT_TABLE,
                "osha_case_number",
            ),
            "days_away": not _has_column(
                inspector,
                _INCIDENT_TABLE,
                "days_away",
            ),
            "days_restricted": not _has_column(
                inspector,
                _INCIDENT_TABLE,
                "days_restricted",
            ),
            "root_cause_method": not _has_column(
                inspector,
                _INCIDENT_TABLE,
                "root_cause_method",
            ),
            "root_cause_tags": not _has_column(
                inspector,
                _INCIDENT_TABLE,
                "root_cause_tags",
            ),
        }
        if any(needs.values()):
            with op.batch_alter_table(_INCIDENT_TABLE) as batch:
                if needs["osha_recordable"]:
                    batch.add_column(
                        sa.Column(
                            "osha_recordable",
                            sa.Boolean(),
                            nullable=False,
                            server_default=sa.false(),
                        )
                    )
                if needs["osha_case_number"]:
                    batch.add_column(
                        sa.Column(
                            "osha_case_number",
                            sa.String(length=32),
                            nullable=True,
                        )
                    )
                if needs["days_away"]:
                    batch.add_column(sa.Column("days_away", sa.Integer(), nullable=True))
                if needs["days_restricted"]:
                    batch.add_column(
                        sa.Column(
                            "days_restricted",
                            sa.Integer(),
                            nullable=True,
                        )
                    )
                if needs["root_cause_method"]:
                    batch.add_column(
                        sa.Column(
                            "root_cause_method",
                            sa.String(length=32),
                            nullable=True,
                        )
                    )
                if needs["root_cause_tags"]:
                    batch.add_column(
                        sa.Column(
                            "root_cause_tags",
                            sa.JSON(),
                            nullable=True,
                            server_default="[]",
                        )
                    )

        # Re-inspect because batch_alter_table on SQLite re-creates the table.
        inspector = sa.inspect(bind)
        if _has_column(inspector, _INCIDENT_TABLE, "osha_recordable") and not _has_index(
            inspector,
            _INCIDENT_TABLE,
            _IX_INCIDENT_RECORDABLE,
        ):
            try:
                op.create_index(
                    _IX_INCIDENT_RECORDABLE,
                    _INCIDENT_TABLE,
                    ["osha_recordable"],
                )
            except Exception:  # noqa: BLE001 — idempotent guard
                pass

    # ── 2. Create the slim CorrectiveAction (FSM) table ──────────────────
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _CA_TABLE):
        users_present = _has_table(inspector, _USERS_TABLE)

        if users_present:
            assigned_col = sa.Column(
                "assigned_to_user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_USERS_TABLE}.id",
                    name=_FK_CA_ASSIGNED,
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
            verified_col = sa.Column(
                "verified_by_user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_USERS_TABLE}.id",
                    name=_FK_CA_VERIFIED,
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        else:
            assigned_col = sa.Column(
                "assigned_to_user_id",
                sa.String(length=36),
                nullable=True,
            )
            verified_col = sa.Column(
                "verified_by_user_id",
                sa.String(length=36),
                nullable=True,
            )

        op.create_table(
            _CA_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "incident_id",
                sa.String(length=36),
                # No FK — keep cross-module coupling loose, same pattern as
                # oe_hse_advanced_incident_investigation.incident_ref.
                nullable=False,
            ),
            sa.Column("description", sa.Text(), nullable=False),
            assigned_col,
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            verified_col,
            sa.Column(
                "verified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "verification_notes",
                sa.Text(),
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
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, _CA_TABLE) and not _has_index(inspector, _CA_TABLE, _IX_CA_INCIDENT):
        try:
            op.create_index(_IX_CA_INCIDENT, _CA_TABLE, ["incident_id"])
        except Exception:  # noqa: BLE001
            pass
    if _has_table(inspector, _CA_TABLE) and not _has_index(inspector, _CA_TABLE, _IX_CA_STATUS):
        try:
            op.create_index(_IX_CA_STATUS, _CA_TABLE, ["status"])
        except Exception:  # noqa: BLE001
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop the new corrective-action table first (FK to users is SET NULL,
    # so users-side cascade is not a concern).
    if _has_index(inspector, _CA_TABLE, _IX_CA_STATUS):
        op.drop_index(_IX_CA_STATUS, table_name=_CA_TABLE)
    if _has_index(inspector, _CA_TABLE, _IX_CA_INCIDENT):
        op.drop_index(_IX_CA_INCIDENT, table_name=_CA_TABLE)
    if _has_table(inspector, _CA_TABLE):
        op.drop_table(_CA_TABLE)

    inspector = sa.inspect(bind)
    if _has_index(inspector, _INCIDENT_TABLE, _IX_INCIDENT_RECORDABLE):
        op.drop_index(
            _IX_INCIDENT_RECORDABLE,
            table_name=_INCIDENT_TABLE,
        )

    if _has_table(inspector, _INCIDENT_TABLE):
        drops: list[str] = []
        # Drop in the reverse of the add order so SQLite batch rebuilds
        # do not leave a half-shaped table behind.
        for col in (
            "root_cause_tags",
            "root_cause_method",
            "days_restricted",
            "days_away",
            "osha_case_number",
            "osha_recordable",
        ):
            if _has_column(inspector, _INCIDENT_TABLE, col):
                drops.append(col)
        if drops:
            with op.batch_alter_table(_INCIDENT_TABLE) as batch:
                for col in drops:
                    batch.drop_column(col)
