# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Requirements: ISO 19650 EIR deliverable matrix.

Wave 4 / T13 - gives the requirements module an integrated BIM and
scheduling suite style EIR (Employer Information Requirements) traceability
ledger. Each requirement can demand one or more deliverables (model,
drawing, schedule, report, COBie, PSET) at a target LOD/LOI per
BIMForum / ISO 19650, due at a project milestone.

The matrix view (rows = requirements, cols = deliverable types) reads
straight off this table — no schema discriminator needed in the
requirement row itself.

Strictly additive — no FK back to the deliverable on the requirement
table, no NOT NULL columns added elsewhere. SQLite-safe (GUID() ⇒
VARCHAR(36)). Inspector-guarded so re-runs on a partially-migrated DB
skip work already done.

Revision ID: v3094_requirement_deliverables
Revises: v3087_merge_wave2_heads
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3094_requirement_deliverables"
down_revision: Union[str, Sequence[str], None] = "v3087_merge_wave2_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_requirement_deliverable"
_REQ_TABLE = "oe_requirements_item"


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
    """Create the requirement-deliverable matrix table."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
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
                "requirement_id",
                guid_type,
                sa.ForeignKey(f"{_REQ_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # model | drawing | schedule | report | cobie | pset | other
            sa.Column("deliverable_type", sa.String(64), nullable=False),
            # BIMForum LOD: 100 | 200 | 300 | 350 | 400 | 500 (string keeps
            # the "LOD 350" pattern readable in exports).
            sa.Column("lod", sa.String(8), nullable=True),
            # ISO 19650 LOI: 1 | 2 | 3 | 4 | 5
            sa.Column("loi", sa.String(8), nullable=True),
            sa.Column("due_milestone_id", guid_type, nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        )

        existing = _existing_index_names(inspector, _TABLE)
        # Composite lookup — matrix view reads rows by (requirement,
        # deliverable_type) when building a row's cell map.
        ix_req_type = "ix_oe_requirement_deliverable_req_type"
        if ix_req_type not in existing:
            try:
                op.create_index(
                    ix_req_type,
                    _TABLE,
                    ["requirement_id", "deliverable_type"],
                )
            except sa.exc.OperationalError:
                pass

        # Single-column index on requirement_id so the cascade delete
        # path doesn't scan the whole table when a requirement is dropped.
        ix_req = "ix_oe_requirement_deliverable_requirement_id"
        if ix_req not in existing:
            try:
                op.create_index(ix_req, _TABLE, ["requirement_id"])
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    """Drop the requirement-deliverable matrix table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        existing = _existing_index_names(inspector, _TABLE)
        for ix in (
            "ix_oe_requirement_deliverable_req_type",
            "ix_oe_requirement_deliverable_requirement_id",
        ):
            if ix in existing:
                try:
                    op.drop_index(ix, table_name=_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_TABLE)
