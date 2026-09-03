# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow: the reference counter.

Creates ``oe_register_workflow_counter`` - one row per reference prefix
holding the last number ISSUED.

Why the table exists: references were computed as MAX+1 of the ones
already on a project, which made them per-project and three digits. Two
jobs both held an ``RFI-004``, so a forwarded reply carrying only its
reference was ambiguous, and deleting an item let its number be handed to
a different piece of work. A counter is monotonic and never re-issues.

Existing rows are NOT rewritten. An item that was raised as ``RFQ-004``
keeps that reference forever - it is on emails that have already left the
building, and rewriting history to tidy a format would break the one
thing a reference is for. The counter is seeded from the highest number
already in use per prefix, so the first new mint continues the series
rather than colliding with it.

Idempotent and inspector-guarded, like v0001.

Revision ID: oe_register_workflow_v0002_reference_counter
Revises: oe_register_workflow_v0001_initial
Create Date: 2026-08-19
"""

from __future__ import annotations

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "oe_register_workflow_v0002_reference_counter"
down_revision: Union[str, Sequence[str], None] = "oe_register_workflow_v0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ITEM = "oe_register_workflow_item"
_COUNTER = "oe_register_workflow_counter"

#: Mirrors templates.KIND_PREFIX. Duplicated deliberately: a migration
#: must not import application code, which may have moved on by the time
#: this runs on an old database.
_PREFIXES = ("RFI", "RFQ", "ORD", "VO", "DEL", "TBX")


def _has(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has(inspector, _COUNTER):
        op.create_table(
            _COUNTER,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("prefix", sa.String(12), nullable=False),
            sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_unique_constraint(f"uq_{_COUNTER}_prefix", _COUNTER, ["prefix"])
        op.create_index(f"ix_{_COUNTER}_prefix", _COUNTER, ["prefix"])

    # Seed from what is already issued, so the first new mint continues
    # the series instead of colliding with a live reference.
    if not _has(inspector, _ITEM):
        return
    existing = {
        str(r[0])
        for r in bind.execute(sa.text(f"SELECT prefix FROM {_COUNTER}")).fetchall()  # noqa: S608
    }
    refs = [
        str(r[0] or "")
        for r in bind.execute(sa.text(f"SELECT reference FROM {_ITEM}")).fetchall()  # noqa: S608
    ]
    for prefix in _PREFIXES:
        if prefix in existing:
            continue
        highest = 0
        for ref in refs:
            # Both shapes: "RFQ-004" and "REG-RFQ-000123".
            if not re.search(rf"(^|-){re.escape(prefix)}-\d+$", ref):
                continue
            m = re.search(r"(\d+)$", ref)
            if m:
                highest = max(highest, int(m.group(1)))
        bind.execute(
            sa.text(
                f"INSERT INTO {_COUNTER} (id, prefix, value) "  # noqa: S608
                "VALUES (:id, :prefix, :value)"
            ),
            {"id": f"counter-{prefix.lower()}", "prefix": prefix, "value": highest},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has(inspector, _COUNTER):
        op.drop_table(_COUNTER)
