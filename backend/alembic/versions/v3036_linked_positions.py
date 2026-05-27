# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Issue #127 — BOQ code reuse / linked positions.

Three additive, nullable columns on ``oe_boq_position`` that let the same
user-facing code be reused across many positions while the per-line
``ordinal`` stays unique (GAEB X83 RNoPart/ID identity +
``boq_quality.no_duplicate_ordinals`` are NOT affected):

* ``reference_code`` (varchar(64), nullable, indexed) — the reusable
  user-facing code (Sección/Partida/Recurso). Distinct from ``ordinal``.
  Auto-generated "R-XXXXXXXX" by the service when the client supplies
  none, so every position is referenceable.
* ``link_group_id`` (GUID/varchar(36), nullable, indexed) — positions
  that share one master definition carry the same group id.
* ``link_role`` (varchar(16), nullable) — 'master' | 'instance';
  NULL means standalone.

All nullable with no server_default so every existing row stays valid
(NULL link_role = standalone, behaves exactly as before this migration).

Idempotent: guarded by an inspector so re-running after SQLite's
``Base.metadata.create_all`` (dev) is a no-op; Postgres prod gets the DDL.

Revision ID: v3036_linked_positions
Revises: v3035_project_profile
Created: 2026-05-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3036_linked_positions"
down_revision: Union[str, Sequence[str], None] = "v3035_project_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_boq_position"


def upgrade() -> None:
    """Add reference_code / link_group_id / link_role to oe_boq_position."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns(_TABLE)}
    existing_indexes = {i["name"] for i in inspector.get_indexes(_TABLE)}

    if "reference_code" not in existing_cols:
        op.add_column(
            _TABLE,
            sa.Column("reference_code", sa.String(length=64), nullable=True),
        )
        if "ix_oe_boq_position_reference_code" not in existing_indexes:
            op.create_index(
                "ix_oe_boq_position_reference_code",
                _TABLE,
                ["reference_code"],
            )

    if "link_group_id" not in existing_cols:
        op.add_column(
            _TABLE,
            sa.Column("link_group_id", sa.String(length=36), nullable=True),
        )
        if "ix_oe_boq_position_link_group_id" not in existing_indexes:
            op.create_index(
                "ix_oe_boq_position_link_group_id",
                _TABLE,
                ["link_group_id"],
            )

    if "link_role" not in existing_cols:
        op.add_column(
            _TABLE,
            sa.Column("link_role", sa.String(length=16), nullable=True),
        )


def downgrade() -> None:
    """Drop the three linked-position columns and their indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns(_TABLE)}
    existing_indexes = {i["name"] for i in inspector.get_indexes(_TABLE)}

    if "link_role" in existing_cols:
        op.drop_column(_TABLE, "link_role")

    if "ix_oe_boq_position_link_group_id" in existing_indexes:
        op.drop_index("ix_oe_boq_position_link_group_id", table_name=_TABLE)
    if "link_group_id" in existing_cols:
        op.drop_column(_TABLE, "link_group_id")

    if "ix_oe_boq_position_reference_code" in existing_indexes:
        op.drop_index("ix_oe_boq_position_reference_code", table_name=_TABLE)
    if "reference_code" in existing_cols:
        op.drop_column(_TABLE, "reference_code")
