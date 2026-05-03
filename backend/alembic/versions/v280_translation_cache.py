"""v2.8.0 — translation cache table.

Adds the ``oe_translation_cache`` table to the main application database
so deployments that prefer a single-file backup (multi-tenant SaaS) can
keep translation history in the same DB as the rest of the application
state.

Note that the standalone TranslationCache class (see
``app/core/translation/cache.py``) also creates the table at runtime in
its own SQLite file (``~/.openestimate/translations/cache.db``). The
schemas are identical so the two stores can be merged later without a
column reshuffle.

Inspector-guarded so re-running the migration on an already-migrated DB
is a no-op (matches the v260c / v290 pattern).

Revision ID: v280_translation_cache
Revises: v290_dashboards_presets
Create Date: 2026-05-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v280_translation_cache"
down_revision: Union[str, Sequence[str], None] = "v2b1_compound_type_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_translation_cache"
_UQ = "uq_oe_translation_cache_key"
_LANGS_IX = "ix_oe_translation_cache_langs"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("text_hash", sa.String(length=40), nullable=False),
        sa.Column("source_lang", sa.String(length=8), nullable=False),
        sa.Column("target_lang", sa.String(length=8), nullable=False),
        sa.Column(
            "domain",
            sa.String(length=64),
            nullable=False,
            server_default="construction",
        ),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("tier_used", sa.String(length=32), nullable=False),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "usage_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "text_hash",
            "source_lang",
            "target_lang",
            "domain",
            name=_UQ,
        ),
    )
    op.create_index(
        _LANGS_IX,
        _TABLE,
        ["source_lang", "target_lang"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    existing_ix = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if _LANGS_IX in existing_ix:
        op.drop_index(_LANGS_IX, table_name=_TABLE)
    op.drop_table(_TABLE)
