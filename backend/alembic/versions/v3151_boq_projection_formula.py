# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ quantity projection: per-element formulas + binding/projection split.

Option C — split a quantity link's two concerns:

* the **binding** (*which* BIM elements) → ``oe_bim_boq_link`` (already
  exists, one row per element);
* the **projection** (*how* to compute) → ``oe_boq_quantity_link`` (this
  table), now enriched with a projection mode + a per-element formula.

Schema:

* ``projection_kind`` (``simple`` | ``formula``) — ``simple`` aggregates a
  single canonical quantity key; ``formula`` evaluates a per-element
  expression (e.g. ``area_m2 * 2``) then aggregates.
* ``formula`` (Text, nullable) — the expression, formula mode only.

Data migration: the old ``element_stable_ids`` JSON on each quantity link
held the binding inline. Each id is resolved to a ``oe_bim_element`` row
(by ``model_id`` + ``stable_id``, falling back to a literal element id)
and materialised as an ``oe_bim_boq_link`` binding row, then the inline
list is emptied so the binding lives in exactly one place. Idempotent:
existing bindings are not duplicated (the table's
``uq_bim_boq_link_pos_elem`` is honoured by an explicit existence check).

Idempotent + portable (SQLite dev + Postgres prod): every column add is
guarded by an inspector and uses ``String(36)`` GUID-compatible ids.

Revision ID: v3151_boq_projection_formula
Revises: v3150_file_favorites
Create Date: 2026-05-29
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3151_boq_projection_formula"
down_revision: Union[str, Sequence[str], None] = "v3150_file_favorites"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_QLINK = "oe_boq_quantity_link"
_BINDING = "oe_bim_boq_link"
_ELEMENT = "oe_bim_element"


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _migrate_bindings(bind: sa.engine.Connection) -> None:
    """Materialise inline ``element_stable_ids`` into ``oe_bim_boq_link``."""
    inspector = sa.inspect(bind)
    if not all(t in inspector.get_table_names() for t in (_QLINK, _BINDING, _ELEMENT)):
        return

    rows = bind.execute(
        sa.text(
            f"SELECT id, position_id, model_id, element_stable_ids "  # noqa: S608 - static table names
            f"FROM {_QLINK}"
        )
    ).fetchall()

    moved = 0
    for link_id, position_id, model_id, raw_ids in rows:
        try:
            stable_ids = json.loads(raw_ids) if isinstance(raw_ids, str) else (raw_ids or [])
        except (TypeError, ValueError):
            stable_ids = []
        if not stable_ids:
            continue

        for sid in stable_ids:
            sid = str(sid).strip()
            if not sid:
                continue
            # Resolve stable_id → element id (scoped to the link's model);
            # fall back to treating sid as a literal element id.
            element_id = bind.execute(
                sa.text(
                    f"SELECT id FROM {_ELEMENT} "  # noqa: S608 - static table names
                    f"WHERE model_id = :mid AND stable_id = :sid LIMIT 1"
                ),
                {"mid": model_id, "sid": sid},
            ).scalar()
            if element_id is None:
                element_id = bind.execute(
                    sa.text(f"SELECT id FROM {_ELEMENT} WHERE id = :sid LIMIT 1"),  # noqa: S608
                    {"sid": sid},
                ).scalar()
            if element_id is None:
                continue  # stale id — skip, nothing to bind

            already = bind.execute(
                sa.text(
                    f"SELECT 1 FROM {_BINDING} "  # noqa: S608 - static table names
                    f"WHERE boq_position_id = :pid AND bim_element_id = :eid LIMIT 1"
                ),
                {"pid": position_id, "eid": element_id},
            ).scalar()
            if already:
                continue

            bind.execute(
                sa.text(
                    f"INSERT INTO {_BINDING} "  # noqa: S608 - static table names
                    f"(id, boq_position_id, bim_element_id, link_type) "
                    f"VALUES (:id, :pid, :eid, 'manual')"
                ),
                {"id": str(uuid.uuid4()), "pid": position_id, "eid": element_id},
            )
            moved += 1

        # Inline binding now lives in oe_bim_boq_link — empty the legacy list.
        bind.execute(
            sa.text(
                f"UPDATE {_QLINK} SET element_stable_ids = '[]' WHERE id = :id"  # noqa: S608
            ),
            {"id": link_id},
        )

    logger.info("v3151 projection: materialised %d binding row(s) from quantity links", moved)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, _QLINK, "projection_kind"):
        op.add_column(
            _QLINK,
            sa.Column(
                "projection_kind",
                sa.String(length=16),
                nullable=False,
                server_default="simple",
            ),
        )
    if not _has_column(inspector, _QLINK, "formula"):
        op.add_column(_QLINK, sa.Column("formula", sa.Text(), nullable=True))

    # Data migration runs after the columns exist so a partially-applied
    # re-run still empties any inline lists it materialised before.
    _migrate_bindings(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Binding rows created by the data migration are intentionally LEFT in
    # place — they are the canonical binding now and dropping them would
    # lose user intent. Only the projection columns are reversed.
    if _has_column(inspector, _QLINK, "formula"):
        op.drop_column(_QLINK, "formula")
    if _has_column(inspector, _QLINK, "projection_kind"):
        op.drop_column(_QLINK, "projection_kind")
