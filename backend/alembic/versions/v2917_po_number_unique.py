"""v2.9.17 — unique (project_id, po_number) on oe_procurement_po.

Mirrors the changeorders ``uq_changeorders_project_code`` fix (BUG-354):
without this constraint the ``MAX(po_number) + 1`` generator in
``PurchaseOrderRepository.next_po_number`` is racy — two concurrent
``create_po`` calls can both compute the same suffix and both succeed,
producing duplicate PO numbers within the same project.

Inspector-guarded so re-running on an already-migrated DB is a no-op.
Pre-existing duplicate ``(project_id, po_number)`` rows are de-duplicated
by appending an ``-N`` ordinal suffix to all but the oldest before the
constraint is created; otherwise SQLite/Postgres would refuse to apply it.

Revision ID: v2917_po_number_unique
Revises: v2916_project_budget_currency
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2917_po_number_unique"
down_revision: Union[str, Sequence[str], None] = "v2916_project_budget_currency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_procurement_po"
_UQ = "uq_procurement_po_project_number"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_unique(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    for uc in inspector.get_unique_constraints(table):
        if uc.get("name") == name:
            return True
    return False


def _dedupe_existing(bind: sa.engine.Connection) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT id, project_id, po_number, created_at FROM oe_procurement_po "
            "ORDER BY project_id, po_number, created_at, id"
        )
    ).fetchall()
    seen: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.project_id), str(row.po_number))
        if key not in seen:
            seen[key] = 1
            continue
        seen[key] += 1
        new_number = f"{row.po_number}-{seen[key]}"
        bind.execute(
            sa.text("UPDATE oe_procurement_po SET po_number = :new WHERE id = :rid"),
            {"new": new_number, "rid": row.id},
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if _has_unique(inspector, _TABLE, _UQ):
        return
    _dedupe_existing(bind)
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_unique_constraint(_UQ, ["project_id", "po_number"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if not _has_unique(inspector, _TABLE, _UQ):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_UQ, type_="unique")
