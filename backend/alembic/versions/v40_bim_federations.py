# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM Federation: per-discipline model grouping (v4.0 / Slice 1).

Adds two strictly-additive tables:

* ``oe_bim_federation`` — federation header (shared origin, name,
  shared display unit) scoped to a project.
* ``oe_bim_federation_model`` — N:1 link rows binding existing
  ``oe_bim_model`` rows to a federation with discipline + z-order +
  per-member display hints. ``ON DELETE CASCADE`` on both FK sides so
  removing a federation or a constituent BIM model cleans up the
  membership rows automatically.

Idempotent — inspector-guarded so re-runs on a partially migrated DB
skip already-present tables/indexes. SQLite-safe via GUID()→VARCHAR(36)
and JSON columns stored as TEXT.

Sits at the tail of the v40 chain (assembly_templates → ai_agents →
cpm_weekly → bim_federations) — linearized during integration so the
slice ships from a single alembic head.

Revision ID: v40_bim_federations
Revises: v40_cpm_weekly
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v40_bim_federations"
down_revision: Union[str, Sequence[str], None] = "v40_cpm_weekly"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FEDERATION_TABLE = "oe_bim_federation"
_FEDERATION_MEMBER_TABLE = "oe_bim_federation_model"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create the federation header + membership tables."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    # ── Federation header ──
    if not _has_table(inspector, _FEDERATION_TABLE):
        op.create_table(
            _FEDERATION_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "origin_offset",
                sa.JSON(),
                nullable=False,
                server_default=sa.text('\'{"x":0,"y":0,"z":0}\''),
            ),
            sa.Column(
                "shared_units",
                sa.String(20),
                nullable=False,
                server_default="m",
            ),
        )
        existing_ix = _existing_index_names(inspector, _FEDERATION_TABLE)
        ix_project = "ix_bim_federation_project"
        if ix_project not in existing_ix:
            try:
                op.create_index(ix_project, _FEDERATION_TABLE, ["project_id"])
            except sa.exc.OperationalError:
                pass

    # ── Federation member link table ──
    if not _has_table(inspector, _FEDERATION_MEMBER_TABLE):
        op.create_table(
            _FEDERATION_MEMBER_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "federation_id",
                guid_type,
                sa.ForeignKey(
                    f"{_FEDERATION_TABLE}.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "bim_model_id",
                guid_type,
                sa.ForeignKey(
                    "oe_bim_model.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "discipline",
                sa.String(50),
                nullable=False,
                server_default="other",
            ),
            sa.Column("color_hint", sa.String(20), nullable=True),
            sa.Column(
                "visible",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1") if is_sqlite else sa.text("true"),
            ),
            sa.Column(
                "z_order",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.UniqueConstraint(
                "federation_id",
                "bim_model_id",
                name="uq_bim_federation_model_pair",
            ),
        )
        existing_ix = _existing_index_names(inspector, _FEDERATION_MEMBER_TABLE)
        for ix_name, cols in (
            ("ix_bim_federation_model_fed", ["federation_id"]),
            ("ix_bim_federation_model_model", ["bim_model_id"]),
        ):
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, _FEDERATION_MEMBER_TABLE, cols)
                except sa.exc.OperationalError:
                    pass


def downgrade() -> None:
    """Drop the federation tables (members first, then header)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _FEDERATION_MEMBER_TABLE):
        existing_ix = _existing_index_names(inspector, _FEDERATION_MEMBER_TABLE)
        for ix in (
            "ix_bim_federation_model_fed",
            "ix_bim_federation_model_model",
        ):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_FEDERATION_MEMBER_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_FEDERATION_MEMBER_TABLE)

    if _has_table(inspector, _FEDERATION_TABLE):
        existing_ix = _existing_index_names(inspector, _FEDERATION_TABLE)
        if "ix_bim_federation_project" in existing_ix:
            try:
                op.drop_index(
                    "ix_bim_federation_project",
                    table_name=_FEDERATION_TABLE,
                )
            except sa.exc.OperationalError:
                pass
        op.drop_table(_FEDERATION_TABLE)
