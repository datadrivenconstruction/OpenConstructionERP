# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Scope the offline sync ledger's unique key by project.

``oe_field_sync_ledger`` was unique on ``client_op_id`` alone, so an op id replayed
against another project returned that project's result and the key blocked a
second row. The key is now ``(project_id, client_op_id)``. Inspector-guarded so a
database the runtime already built from the models is a no-op.

Revision ID: vfsl01_field_sync_ledger_project
Revises: vtel01_util_counter_reset
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "vfsl01_field_sync_ledger_project"
down_revision = "vtel01_util_counter_reset"
branch_labels = None
depends_on = None

_TABLE = "oe_field_sync_ledger"
_OLD = "uq_oe_field_sync_ledger_client_op_id"
_NEW = "uq_oe_field_sync_ledger_project_op"


def _uniques(insp: sa.Inspector) -> set[str]:
    return {u["name"] for u in insp.get_unique_constraints(_TABLE)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    names = _uniques(insp)
    if _OLD in names:
        op.drop_constraint(_OLD, _TABLE, type_="unique")
    if _NEW not in names:
        op.create_unique_constraint(_NEW, _TABLE, ["project_id", "client_op_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    names = _uniques(insp)
    if _NEW in names:
        op.drop_constraint(_NEW, _TABLE, type_="unique")
    if _OLD not in names:
        op.create_unique_constraint(_OLD, _TABLE, ["client_op_id"])
