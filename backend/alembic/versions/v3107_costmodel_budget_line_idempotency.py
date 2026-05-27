# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""costmodel — idempotency unique index for budget lines.

R5 audit (May 2026): ``generate_budget_from_boq`` had no idempotency
guard — re-running it silently duplicated budget lines for the same BOQ
positions, doubling the project BAC and poisoning every downstream
EVM rollup. The service now skips already-wired positions in process,
and this migration adds a DB-level partial unique index so a race or a
direct repo call cannot bypass it either.

Strictly additive + inspector-guarded so a fresh install with
``Base.metadata.create_all`` applied is a no-op. Includes a one-time
dedupe pass that keeps the oldest line per ``(project_id,
boq_position_id)`` so existing installs can upgrade cleanly.

Down-revision: v3106_geo_hub_init (current single head).

Revision ID: v3107_costmodel_idempotency
Revises: v3106_geo_hub_init
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3107_costmodel_idempotency"
down_revision: Union[str, Sequence[str], None] = "v3106_geo_hub_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Inspector helpers ───────────────────────────────────────────────────


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


# ── upgrade ─────────────────────────────────────────────────────────────


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Dedupe pre-existing duplicates so the index can be created ─────
    # On fresh installs this is a no-op. On existing installs that ran
    # the buggy ``generate_budget_from_boq`` we keep the oldest row per
    # (project_id, boq_position_id) and delete the rest. Manual lines
    # (boq_position_id IS NULL) are never touched.
    if _has_table(inspector, "oe_costmodel_budget_line"):
        op.execute(
            sa.text(
                """
                DELETE FROM oe_costmodel_budget_line
                WHERE id IN (
                    SELECT b.id FROM oe_costmodel_budget_line b
                    JOIN (
                        SELECT project_id, boq_position_id,
                               MIN(created_at) AS keep_at
                        FROM oe_costmodel_budget_line
                        WHERE boq_position_id IS NOT NULL
                        GROUP BY project_id, boq_position_id
                        HAVING COUNT(*) > 1
                    ) k
                    ON b.project_id = k.project_id
                    AND b.boq_position_id = k.boq_position_id
                    AND b.created_at > k.keep_at
                )
                """
            )
        )

    # ── Partial unique on (project_id, boq_position_id) ────────────────
    # Both PostgreSQL and SQLite (3.8.0+) support partial indexes. The
    # ``WHERE boq_position_id IS NOT NULL`` clause is essential — manual
    # budget lines NOT linked to a BOQ position remain duplicable.
    if _has_table(inspector, "oe_costmodel_budget_line") and not _has_index(
        inspector,
        "oe_costmodel_budget_line",
        "uq_oe_costmodel_budget_line_project_position",
    ):
        op.create_index(
            "uq_oe_costmodel_budget_line_project_position",
            "oe_costmodel_budget_line",
            ["project_id", "boq_position_id"],
            unique=True,
            sqlite_where=sa.text("boq_position_id IS NOT NULL"),
            postgresql_where=sa.text("boq_position_id IS NOT NULL"),
        )


# ── downgrade ───────────────────────────────────────────────────────────


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(
        inspector,
        "oe_costmodel_budget_line",
        "uq_oe_costmodel_budget_line_project_position",
    ):
        op.drop_index(
            "uq_oe_costmodel_budget_line_project_position",
            table_name="oe_costmodel_budget_line",
        )
