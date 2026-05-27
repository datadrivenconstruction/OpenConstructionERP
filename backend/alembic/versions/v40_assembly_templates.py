# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Assembly Library: platform-wide canonical templates (v4.0 / Slice 1).

Adds a single strictly-additive table ``oe_assemblies_template`` that
holds catalogue-agnostic, read-only recipe templates (concrete walls,
brick walls, drywall, slabs, roofs, doors, windows, finishes, MEP,
columns, beams, excavation). Each component is described by a free-text
``cost_match_query`` so the apply endpoint can re-resolve the line
against the project's bound cost catalogue at runtime via the existing
``costs.matcher`` lexical/semantic search — never hard-coded ids.

Idempotent — inspector-guarded so re-runs on a partially migrated DB
skip already-present tables/indexes. SQLite-safe via GUID()→VARCHAR(36)
and JSON columns stored as TEXT.

Revision ID: v40_assembly_templates
Revises: v3096_regional_indices_certainty
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v40_assembly_templates"
down_revision: Union[str, Sequence[str], None] = "v3096_regional_indices_certainty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TEMPLATE_TABLE = "oe_assemblies_template"


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
    """Create the assembly-templates table + supporting indexes."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TEMPLATE_TABLE):
        op.create_table(
            _TEMPLATE_TABLE,
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
            # Canonical English name; unique key the seeder upserts on.
            sa.Column("name", sa.String(255), nullable=False),
            # Localised display names: {"de": "...", "ru": "...", "es": "..."}.
            sa.Column(
                "name_translations",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            # Coarse bucket: concrete | masonry | drywall | mep | ...
            sa.Column(
                "category",
                sa.String(100),
                nullable=False,
                server_default="",
            ),
            # Output unit of the recipe: m, m2, m3, kg, pcs, set, h, ...
            sa.Column("unit", sa.String(20), nullable=False, server_default=""),
            # Component list. Each item is a dict with cost_match_query,
            # factor, unit, role and a description (see templates_seed.py).
            sa.Column(
                "components",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            # {"din276": "330", "masterformat": "04 20 00"}
            sa.Column(
                "classification",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column(
                "tags",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            # Distinguishes platform-shipped seeds from future
            # user-contributed templates.
            sa.Column(
                "is_builtin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1") if is_sqlite else sa.text("true"),
            ),
            sa.UniqueConstraint("name", name="uq_oe_assemblies_template_name"),
        )

        existing_ix = _existing_index_names(inspector, _TEMPLATE_TABLE)
        ix_category = "ix_oe_assemblies_template_category"
        if ix_category not in existing_ix:
            try:
                op.create_index(ix_category, _TEMPLATE_TABLE, ["category"])
            except sa.exc.OperationalError:
                pass
        ix_name = "ix_oe_assemblies_template_name"
        if ix_name not in existing_ix:
            try:
                op.create_index(ix_name, _TEMPLATE_TABLE, ["name"])
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    """Drop the assembly-templates table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TEMPLATE_TABLE):
        existing_ix = _existing_index_names(inspector, _TEMPLATE_TABLE)
        for ix in (
            "ix_oe_assemblies_template_category",
            "ix_oe_assemblies_template_name",
        ):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_TEMPLATE_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_TEMPLATE_TABLE)
