# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3.11.0 — Risk Register Monte Carlo (PERT) columns.

Adds the PERT three-point estimate columns + the persisted-simulation
JSON blob to ``oe_risk_register``. Together these power the Monte Carlo
simulation (T1 / Wave 1) - equivalent in spirit to what schedule risk
analysis tools expose for schedule + cost risk:

* ``cost_p10`` / ``cost_p50`` / ``cost_p90``  — optimistic / most-likely /
  pessimistic cost impact (currency-neutral; the project's currency is
  the unit).
* ``schedule_p10`` / ``schedule_p50`` / ``schedule_p90`` — same three
  points for schedule slip, in days.
* ``last_simulation`` — JSON snapshot of the most recent run
  (iterations, P50/P80/P95, histogram bins, tornado contributors). The
  service writes one row per risk so the frontend can drill in even
  without re-running.

All columns are nullable so the qualitative 5x5 scoring path (still the
default) keeps working untouched — a risk with no PERT triple just
contributes zero to the simulated distribution.

SQLite-safe via ``batch_alter_table`` and inspector-guarded so re-running
the migration on a partially-migrated DB is a no-op. Fully reversible.

Revision ID: v3080_risk_pert_columns
Revises: v3071_merge_clash_and_files
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3080_risk_pert_columns"
down_revision: Union[str, Sequence[str], None] = "v3071_merge_clash_and_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_risk_register"

# Column name -> SQLAlchemy type factory. Kept declarative so upgrade and
# downgrade walk the same list in opposite directions.
_NEW_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("cost_p10", sa.Numeric(18, 2)),
    ("cost_p50", sa.Numeric(18, 2)),
    ("cost_p90", sa.Numeric(18, 2)),
    ("schedule_p10", sa.Integer()),
    ("schedule_p50", sa.Integer()),
    ("schedule_p90", sa.Integer()),
    ("last_simulation", sa.JSON()),
)


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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return

    missing = [(name, type_) for name, type_ in _NEW_COLUMNS if not _has_column(inspector, _TABLE, name)]
    if not missing:
        return

    # batch_alter_table is required for SQLite to add multiple columns.
    with op.batch_alter_table(_TABLE) as batch:
        for name, type_ in missing:
            batch.add_column(sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return

    present = [name for name, _ in _NEW_COLUMNS if _has_column(inspector, _TABLE, name)]
    if not present:
        return

    with op.batch_alter_table(_TABLE) as batch:
        for name in present:
            batch.drop_column(name)
