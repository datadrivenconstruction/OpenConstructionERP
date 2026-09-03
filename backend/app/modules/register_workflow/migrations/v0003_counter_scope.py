# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow: per-job reference series.

Adds ``scope`` to ``oe_register_workflow_counter`` and moves the unique
constraint from ``prefix`` alone to ``(prefix, scope)``.

Why: a global series produced ``REG-RFI-000001``, which does not say which
job it belongs to. The job number now goes into the reference -
``REG-RFI-25406-0001`` - so each job owns its own series. The job number
is what keeps references unambiguous across the business, which is the
objection that made the series global in the first place.

Existing rows are NOT rewritten. An item raised as ``REG-RFI-000001``
keeps that reference forever: it is on emails that have already left the
building, and rewriting history to tidy a format breaks the one thing a
reference is for. Existing counter rows become the un-scoped series
(``scope = ''``), which is exactly what they were, and which is where
``REG-MSG`` stays.

Idempotent and inspector-guarded, like v0001 and v0002.

Revision ID: oe_register_workflow_v0003_counter_scope
Revises: oe_register_workflow_v0002_reference_counter
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "oe_register_workflow_v0003_counter_scope"
down_revision: Union[str, Sequence[str], None] = "oe_register_workflow_v0002_reference_counter"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COUNTER = "oe_register_workflow_counter"
_UQ = "uq_register_workflow_counter_prefix_scope"


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _COUNTER):
        # v0002 has not run on this database; it creates the table with
        # the current model, so there is nothing to migrate.
        return

    if not _has_column(inspector, _COUNTER, "scope"):
        op.add_column(
            _COUNTER,
            sa.Column("scope", sa.String(40), nullable=False, server_default=""),
        )
        op.create_index(f"ix_{_COUNTER}_scope", _COUNTER, ["scope"])

    # The old UNIQUE on prefix alone would refuse a second job's RFQ
    # series. Drop it whatever it is called, then add the composite.
    for uq in inspector.get_unique_constraints(_COUNTER):
        if uq.get("column_keys") == ["prefix"] and uq.get("name"):
            op.drop_constraint(uq["name"], _COUNTER, type_="unique")
    # Some backends express it as a unique INDEX rather than a constraint.
    for ix in inspector.get_indexes(_COUNTER):
        if ix.get("unique") and ix.get("column_names") == ["prefix"] and ix.get("name"):
            op.drop_index(ix["name"], table_name=_COUNTER)

    existing = {u.get("name") for u in inspector.get_unique_constraints(_COUNTER)}
    if _UQ not in existing:
        op.create_unique_constraint(_UQ, _COUNTER, ["prefix", "scope"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _COUNTER):
        return
    existing = {u.get("name") for u in inspector.get_unique_constraints(_COUNTER)}
    if _UQ in existing:
        op.drop_constraint(_UQ, _COUNTER, type_="unique")
    if _has_column(inspector, _COUNTER, "scope"):
        # Only the un-scoped rows can survive a unique-on-prefix world.
        op.execute(sa.text(f"DELETE FROM {_COUNTER} WHERE scope <> ''"))  # noqa: S608
        op.drop_index(f"ix_{_COUNTER}_scope", table_name=_COUNTER)
        op.drop_column(_COUNTER, "scope")
    op.create_unique_constraint(None, _COUNTER, ["prefix"])
