# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3099 — RFI unique number + attachments column.

Round-5 RFI audit:
1. ``(project_id, rfi_number)`` UNIQUE so concurrent ``create_rfi``
   races on ``max(rfi_number)+1`` surface a clean :class:`IntegrityError`
   the service-layer retry loop can handle, rather than silently writing
   duplicate RFI-007 rows in the same project.
2. ``attachments`` JSON column for reply attachments (server-derived
   relative paths only; magic-byte gated at the router).

Both operations are idempotent + inspector-guarded; the unique constraint
uses batch-mode so SQLite (no ``ALTER TABLE ADD CONSTRAINT``) succeeds.

Revision ID: v3099_rfi
Revises: v3099_eac
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3099_rfi"
down_revision: Union[str, Sequence[str], None] = "v3099_eac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_rfi_rfi"
_ATTACH_COL = "attachments"
_UQ_NAME = "uq_rfi_project_number"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, col: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return col in {c["name"] for c in inspector.get_columns(table)}


def _has_unique_constraint(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {u["name"] for u in inspector.get_unique_constraints(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE) and not _has_column(inspector, _TABLE, _ATTACH_COL):
        op.add_column(
            _TABLE,
            sa.Column(
                _ATTACH_COL,
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
        inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE) and not _has_unique_constraint(
        inspector,
        _TABLE,
        _UQ_NAME,
    ):
        try:
            with op.batch_alter_table(_TABLE) as batch:
                batch.create_unique_constraint(_UQ_NAME, ["project_id", "rfi_number"])
        except sa.exc.OperationalError:
            # Race-safe: another worker added the same constraint.
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_unique_constraint(inspector, _TABLE, _UQ_NAME):
        try:
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_constraint(_UQ_NAME, type_="unique")
        except sa.exc.OperationalError:
            pass

    inspector = sa.inspect(bind)
    if _has_column(inspector, _TABLE, _ATTACH_COL):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_ATTACH_COL)
