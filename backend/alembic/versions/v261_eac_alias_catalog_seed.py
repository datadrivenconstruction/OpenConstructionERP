"""v2.6.0 EAC-2.2 -- seed the built-in alias catalog.

Reads ``app/modules/eac/aliases/seed_catalog.json`` (40 aliases × 9
languages, RFC 35 §6 EAC-2.2) and inserts org-scoped, ``is_built_in=True``
rows so every tenant sees the canonical names out of the box.

The migration is idempotent: a row is only inserted when no row with the
same ``(scope='org', scope_id IS NULL, name=...)`` already exists.
``downgrade()`` removes every ``is_built_in=True`` row so the migration
can be re-applied cleanly.

Revision ID: v261_eac_alias_catalog_seed
Revises: v260a_eac_aliases_tables
Create Date: 2026-04-25
"""

from __future__ import annotations

import json
import uuid
from importlib import resources
from pathlib import Path
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v261_eac_alias_catalog_seed"
down_revision: Union[str, None] = "v260a_eac_aliases_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ALIAS_TABLE = "oe_eac_parameter_aliases"
SYNONYM_TABLE = "oe_eac_alias_synonyms"


def _load_catalog() -> list[dict[str, Any]]:
    """Load the seed JSON via importlib.resources (works in zipapps too).

    Falls back to a direct filesystem read so contributors who run the
    migration without installing the package still see the seed apply.
    """
    try:
        ref = resources.files("app.modules.eac.aliases").joinpath(
            "seed_catalog.json",
        )
        text = ref.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        # Fallback for non-installed checkouts.
        here = Path(__file__).resolve().parent.parent.parent
        text = (
            here / "app" / "modules" / "eac" / "aliases" / "seed_catalog.json"
        ).read_text(encoding="utf-8")
    doc = json.loads(text)
    return doc.get("aliases", [])


def _stable_id() -> str:
    """Generate a UUID for an inserted row (UUIDv4 — non-deterministic).

    Using UUIDv4 rather than UUIDv5 keeps the seed re-runnable without
    exact-id collisions when downgrade ↔ upgrade cycles run on the same
    database during tests.
    """
    return str(uuid.uuid4())


def upgrade() -> None:
    """Insert built-in aliases (skipping rows that already exist)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if ALIAS_TABLE not in insp.get_table_names():
        # Table missing — earlier migration didn't run yet. Skip rather
        # than raise so the alembic chain stays composable in CI.
        return

    aliases = _load_catalog()
    if not aliases:
        return

    alias_meta = sa.table(
        ALIAS_TABLE,
        sa.column("id", sa.String),
        sa.column("scope", sa.String),
        sa.column("scope_id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("value_type_hint", sa.String),
        sa.column("default_unit", sa.String),
        sa.column("version", sa.Integer),
        sa.column("is_built_in", sa.Boolean),
        sa.column("tenant_id", sa.String),
    )
    syn_meta = sa.table(
        SYNONYM_TABLE,
        sa.column("id", sa.String),
        sa.column("alias_id", sa.String),
        sa.column("pattern", sa.String),
        sa.column("kind", sa.String),
        sa.column("case_sensitive", sa.Boolean),
        sa.column("priority", sa.Integer),
        sa.column("pset_filter", sa.String),
        sa.column("source_filter", sa.String),
        sa.column("unit_multiplier", sa.Numeric),
    )

    for alias in aliases:
        name = alias.get("name")
        if not name:
            continue

        existing = bind.execute(
            sa.select(alias_meta.c.id).where(
                alias_meta.c.scope == "org",
                alias_meta.c.scope_id.is_(None),
                alias_meta.c.name == name,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        alias_id = _stable_id()
        # Description is a {lang: str} dict — flatten to the English variant
        # for the column, keep the rest in metadata once i18n storage lands.
        description = alias.get("description")
        if isinstance(description, dict):
            description = description.get("en") or next(
                iter(description.values()), None,
            )
        op.execute(
            alias_meta.insert().values(
                id=alias_id,
                scope="org",
                scope_id=None,
                name=name,
                description=description,
                value_type_hint=alias.get("value_type_hint") or "any",
                default_unit=alias.get("default_unit"),
                version=1,
                is_built_in=True,
                tenant_id=None,
            )
        )

        for syn in alias.get("synonyms") or []:
            op.execute(
                syn_meta.insert().values(
                    id=_stable_id(),
                    alias_id=alias_id,
                    pattern=syn.get("pattern", ""),
                    kind=syn.get("kind") or "exact",
                    case_sensitive=bool(syn.get("case_sensitive", False)),
                    priority=int(syn.get("priority", 100)),
                    pset_filter=syn.get("pset_filter"),
                    source_filter=syn.get("source_filter") or "any",
                    unit_multiplier=str(syn.get("unit_multiplier", "1")),
                )
            )


def downgrade() -> None:
    """Delete every alias seeded with ``is_built_in=True``.

    Synonyms cascade automatically thanks to the FK ``ON DELETE CASCADE``.
    """
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if ALIAS_TABLE not in insp.get_table_names():
        return

    alias_meta = sa.table(
        ALIAS_TABLE,
        sa.column("is_built_in", sa.Boolean),
    )
    op.execute(
        alias_meta.delete().where(alias_meta.c.is_built_in.is_(True))
    )
