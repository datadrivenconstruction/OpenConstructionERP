# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trigram (pg_trgm) index for fuzzy cost-item search.

Cost-item search upgraded from plain substring (ILIKE) matching to fuzzy, ranked
search using PostgreSQL trigram similarity (the pg_trgm extension). This
migration provisions the two database objects that path relies on:

    pg_trgm extension         - enables ``similarity`` / ``word_similarity`` and
                                the trigram operators used to rank results and to
                                broaden recall (typo- and word-order-tolerant
                                matching).
    ix_costs_description_trgm - a GIN trigram index on ``lower(description)`` so
                                the broadened recall and the ILIKE arms stay fast
                                on the 55k+ row multilingual catalogue.

Both steps are best-effort and fully guarded. CREATE EXTENSION needs a superuser
(the embedded cluster qualifies; a locked-down managed cluster may not), so it is
wrapped in try/except and never fails the migration - the service detects pg_trgm
at query time and falls back to ILIKE when it is absent. The index is only built
when the extension is present and uses IF NOT EXISTS plus an inspector guard, so
a re-run is a no-op.

The embedded-PostgreSQL runtime materialises the base table via ``create_all`` at
startup but does NOT run this migration, so that runtime relies on the same
query-time detection; this migration is for external-PostgreSQL deployments that
manage schema with Alembic. Additive: no existing table is touched. PostgreSQL
only, no SQLite shims.

Revision ID: v3189_cost_search_trgm
Revises: v3188_fx_rate_cache
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3189_cost_search_trgm"
down_revision = "v3188_fx_rate_cache"
branch_labels = None
depends_on = None

_TABLE = "oe_costs_item"
_INDEX = "ix_costs_description_trgm"


def _extension_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = :n"), {"n": name}).first()
    return row is not None


def _has_index(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(ix["name"] == name for ix in insp.get_indexes(_TABLE))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # pg_trgm is PostgreSQL-only; nothing to do on other backends.
        return

    # 1. Best-effort enable pg_trgm. It needs a superuser, so never fail the
    #    migration if the cluster forbids it - the service falls back to ILIKE.
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    except Exception:  # noqa: BLE001 - a denied CREATE EXTENSION must not abort the upgrade
        return

    # 2. Only build the GIN trigram index when the extension is actually present
    #    (gin_trgm_ops is defined by pg_trgm) and the index is missing.
    if not _extension_exists("pg_trgm"):
        return
    if _has_index(_INDEX):
        return
    op.execute(f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_TABLE} USING gin (lower(description) gin_trgm_ops)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Drop the index; leave the extension in place - other features may rely on
    # it, and dropping an extension is a heavier, riskier operation.
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
