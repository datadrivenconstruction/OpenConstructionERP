# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ai_estimate: persist USD cost estimate alongside token counts.

Adds one strictly-additive column:

* ``oe_ai_estimate_job.cost_usd_estimate`` (Float, NOT NULL, default 0.0)
  — the USD spend computed at persist time from ``tokens_used`` and the
  shared per-1k rate table in :mod:`app.core.ai.pricing`. Token counts
  alone are not a fair cross-provider unit (Anthropic counts differently
  than OpenAI) so per-tenant rollups need USD to be comparable.

This brings the ``ai`` module to parity with ``clash_ai_triage`` which
has shipped ``cost_usd_estimate`` since v4.1. Both modules now share the
same rate table so cost dashboards can pivot on a single column.

Idempotent — inspector-guarded so re-runs on a partially-migrated DB
skip the add. SQLite-safe (``Float`` -> REAL). Follows the post-v4.4.1
server-default discipline so the ``create_all`` fresh-DB path can't
trip ``IntegrityError`` from a seed insert.

Revision ID: v3128_ai_estimate_cost_usd
Revises: v3127_geo_hub_geocode_cache
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3128_ai_estimate_cost_usd"
down_revision: Union[str, Sequence[str], None] = "v3127_geo_hub_geocode_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_ai_estimate_job"
_COLUMN = "cost_usd_estimate"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_columns(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    """Add ``cost_usd_estimate`` to ``oe_ai_estimate_job`` (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # If the parent table doesn't exist yet (very fresh DB before
    # ``create_all`` has run for this module's models), there's nothing
    # to alter — the eventual ``create_all`` will pick up the column from
    # the model definition. Skip silently.
    if not _has_table(inspector, _TABLE):
        return

    if _COLUMN in _existing_columns(inspector, _TABLE):
        return

    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
    )


def downgrade() -> None:
    """Drop ``cost_usd_estimate`` from ``oe_ai_estimate_job``."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if _COLUMN not in _existing_columns(inspector, _TABLE):
        return
    # batch_alter_table for SQLite compatibility (ALTER DROP COLUMN was
    # only added in SQLite 3.35; the batch helper rebuilds the table).
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
