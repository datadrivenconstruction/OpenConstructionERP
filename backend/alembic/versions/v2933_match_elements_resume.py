# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v2.9.33 — Match Elements: BIM-model binding + resume + archive.

Adds three nullable-with-default columns to ``oe_match_elements_session``
so the rewritten ``/match-elements`` page can:

    * bind a session to a specific BIM model (one project may carry
      several models — architectural / structural / MEP) — ``bim_model_id``;
    * resume a previously opened session instead of creating a fresh
      one on every page load — ``last_active_at`` drives the resume picker;
    * hide stale sessions from the resume picker without losing history —
      ``is_archived``.

The migration is idempotent (skips re-applying columns/indexes that
already exist).

Revision ID: v2933_match_elements_resume
Revises: v2932_match_elements
Create Date: 2026-05-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2933_match_elements_resume"
down_revision: Union[str, Sequence[str], None] = "v2932_match_elements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_match_elements_session"


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
    if not _has_table(inspector, _TABLE):
        return

    if not _has_column(inspector, _TABLE, "bim_model_id"):
        op.add_column(
            _TABLE,
            sa.Column("bim_model_id", sa.String(length=36), nullable=True),
        )
    if not _has_column(inspector, _TABLE, "last_active_at"):
        op.add_column(
            _TABLE,
            sa.Column(
                "last_active_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
    if not _has_column(inspector, _TABLE, "is_archived"):
        op.add_column(
            _TABLE,
            sa.Column(
                "is_archived",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )

    if not _has_index(inspector, _TABLE, "ix_match_session_bim_model"):
        op.create_index(
            "ix_match_session_bim_model",
            _TABLE,
            ["bim_model_id"],
        )
    # Compose project + active filter — the resume picker hits this hot.
    if not _has_index(inspector, _TABLE, "ix_match_session_project_active"):
        op.create_index(
            "ix_match_session_project_active",
            _TABLE,
            ["project_id", "is_archived"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    for idx_name in (
        "ix_match_session_project_active",
        "ix_match_session_bim_model",
    ):
        if _has_index(inspector, _TABLE, idx_name):
            op.drop_index(idx_name, table_name=_TABLE)
    for col_name in ("is_archived", "last_active_at", "bim_model_id"):
        if _has_column(inspector, _TABLE, col_name):
            op.drop_column(_TABLE, col_name)
