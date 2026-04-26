"""v2.6.0 — EacRun: Parquet spool path + idempotency key (Wave 1, RFC 36 W1.1).

Adds two columns to ``oe_eac_run`` so the runner can:

* ``spool_path`` — track where Parquet-spilled result rows live when a
  run produces more than ``HOT_RESULT_ITEM_CAP`` per-element rows. NULL
  when the run fits entirely in the OLTP table.
* ``idempotency_key`` — dedup re-posted runs. Either supplied by the
  client via the ``Idempotency-Key`` header, or derived from
  sha256(ruleset_id + ruleset.updated_at + sorted element stable_ids +
  elements content hash). The unique constraint is per-tenant +
  per-ruleset so two tenants can use the same client-supplied key
  without colliding.

Both columns are nullable so existing rows survive the migration
unchanged. Inspector-guarded so re-running the migration on an already
migrated DB is a no-op (matches the pattern from v280_4d_schedule_eac).

Revision ID: v260b_eac_run_spool_idempotency
Revises: v280_4d_schedule_eac
Create Date: 2026-04-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "v260b_eac_run_spool_idempotency"
down_revision: Union[str, Sequence[str], None] = "v280_4d_schedule_eac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_eac_run"
_SPOOL_COL = "spool_path"
_IDEMP_COL = "idempotency_key"
_IDEMP_INDEX = "ix_eac_run_idempotency_key"
_IDEMP_UNIQUE = "uq_eac_run_idempotency_per_ruleset"


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, col: str) -> bool:
    return col in {c["name"] for c in inspector.get_columns(table)}


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    return name in {i["name"] for i in inspector.get_indexes(table)}


def _has_unique(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    return name in {u["name"] for u in inspector.get_unique_constraints(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        # The base v260 migration must have been run; if not, this is a
        # broken DB and we should fail loudly.
        raise RuntimeError(
            f"{_TABLE} not found — run v260_eac_v2_core first"
        )

    if not _has_column(inspector, _TABLE, _SPOOL_COL):
        op.add_column(
            _TABLE,
            sa.Column(_SPOOL_COL, sa.String(length=512), nullable=True),
        )

    if not _has_column(inspector, _TABLE, _IDEMP_COL):
        op.add_column(
            _TABLE,
            sa.Column(_IDEMP_COL, sa.String(length=128), nullable=True),
        )

    if not _has_index(inspector, _TABLE, _IDEMP_INDEX):
        op.create_index(
            _IDEMP_INDEX,
            _TABLE,
            [_IDEMP_COL],
            unique=False,
        )

    # Unique constraint: same idempotency key cannot belong to two runs
    # of the same (tenant, ruleset). SQLite has no ``ALTER TABLE ADD
    # CONSTRAINT``, so we route through ``batch_alter_table`` — it copies
    # the table on SQLite and emits a plain ALTER on Postgres. The skip
    # check avoids re-adding on already-migrated databases.
    if not _has_unique(inspector, _TABLE, _IDEMP_UNIQUE):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.create_unique_constraint(
                _IDEMP_UNIQUE,
                ["tenant_id", "ruleset_id", _IDEMP_COL],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return

    if _has_unique(inspector, _TABLE, _IDEMP_UNIQUE):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_constraint(_IDEMP_UNIQUE, type_="unique")

    if _has_index(inspector, _TABLE, _IDEMP_INDEX):
        op.drop_index(_IDEMP_INDEX, table_name=_TABLE)

    if _has_column(inspector, _TABLE, _IDEMP_COL):
        op.drop_column(_TABLE, _IDEMP_COL)

    if _has_column(inspector, _TABLE, _SPOOL_COL):
        op.drop_column(_TABLE, _SPOOL_COL)
