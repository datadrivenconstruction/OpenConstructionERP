# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan pins become the one location registry

Adds target, sheet, BIM location, mirrored status and revision state columns to
``oe_plan_pin`` plus a per-project idempotency key, and backfills one pin per punch
item that already carries a drawing coordinate. The punch item keeps its own
coordinates; the pin only references it.

Revision ID: vpin01_plan_pin_targets
Revises: vssomod01_sso_providers
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vpin01_plan_pin_targets"
down_revision: str | Sequence[str] | None = "vssomod01_sso_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PIN = "oe_plan_pin"
_PUNCH = "oe_punchlist_item"
_SHEET = "oe_documents_sheet"

_COLUMNS: list[sa.Column] = [
    sa.Column("target_kind", sa.String(20), nullable=False, server_default="note"),
    sa.Column("target_id", sa.String(36), nullable=True),
    sa.Column("sheet_id", sa.String(36), nullable=True),
    sa.Column("bim_model_id", sa.String(36), nullable=True),
    sa.Column("bim_element_id", sa.String(36), nullable=True),
    sa.Column("bim_xyz", sa.JSON(), nullable=True),
    sa.Column("status", sa.String(40), nullable=True),
    sa.Column("revision_state", sa.String(20), nullable=False, server_default="current"),
    sa.Column("carried_from_pin_id", sa.String(36), nullable=True),
    sa.Column("client_op_id", sa.String(128), nullable=True),
]

_INDEXES = {
    "ix_plan_pin_project_sheet": ["project_id", "sheet_id"],
    "ix_plan_pin_target": ["target_kind", "target_id"],
    "ix_oe_plan_pin_bim_element_id": ["bim_element_id"],
}
_UNIQUE = "uq_plan_pin_project_client_op"


def _insp() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_insp().get_table_names())


def upgrade() -> None:
    """Add the columns, indexes and the idempotency key, then backfill punch pins."""
    if _PIN not in _tables():
        return
    have = {c["name"] for c in _insp().get_columns(_PIN)}
    for col in _COLUMNS:
        if col.name not in have:
            op.add_column(_PIN, col)
    have_ix = {i["name"] for i in _insp().get_indexes(_PIN)}
    for name, cols in _INDEXES.items():
        if name not in have_ix:
            op.create_index(name, _PIN, cols)
    have_uq = {u["name"] for u in _insp().get_unique_constraints(_PIN)} | have_ix
    if _UNIQUE not in have_uq:
        op.create_unique_constraint(_UNIQUE, _PIN, ["project_id", "client_op_id"])
    _backfill_punch_pins()


# data-rewrite-ack: table=oe_plan_pin growth=bounded rows=one pin per placed punch item on first run, then only hand-placed pins
# boot-repair: gap - copies punch coordinates into pins; the boot heal adds the columns empty, and the overlay and the punch page keep reading the punch item's own coordinates, so an install that never runs alembic only lacks the pre-existing punch items in the pin list
def _backfill_punch_pins() -> None:
    if _PUNCH not in _tables() or _SHEET not in _tables():
        return
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_PIN} (id, project_id, document_id, page, x, y, note, created_by,
                                target_kind, target_id, sheet_id, status, revision_state,
                                metadata, created_at, updated_at)
            SELECT gen_random_uuid()::text, p.project_id, btrim(p.document_id), p.page,
                   p.location_x, p.location_y, p.title, p.created_by,
                   'punch', p.id, (
                       SELECT s.id FROM {_SHEET} s
                       WHERE btrim(s.document_id) = btrim(p.document_id) AND s.page_number = p.page
                       ORDER BY s.created_at DESC LIMIT 1
                   ), p.status, 'current', '{{}}', now(), now()
            FROM {_PUNCH} p
            WHERE p.document_id IS NOT NULL AND btrim(p.document_id) <> ''
              AND p.page IS NOT NULL AND p.page >= 1
              AND p.location_x BETWEEN 0 AND 1 AND p.location_y BETWEEN 0 AND 1
              AND NOT EXISTS (
                  SELECT 1 FROM {_PIN} q WHERE q.target_kind = 'punch' AND q.target_id = p.id
              )
            """
        )
    )


def downgrade() -> None:
    """Drop the added columns and indexes (backfilled punch pins go with them)."""
    if _PIN not in _tables():
        return
    op.execute(sa.text(f"DELETE FROM {_PIN} WHERE target_kind = 'punch'"))
    have_ix = {i["name"] for i in _insp().get_indexes(_PIN)}
    have_uq = {u["name"] for u in _insp().get_unique_constraints(_PIN)}
    if _UNIQUE in have_uq:
        op.drop_constraint(_UNIQUE, _PIN, type_="unique")
    for name in _INDEXES:
        if name in have_ix:
            op.drop_index(name, table_name=_PIN)
    have = {c["name"] for c in _insp().get_columns(_PIN)}
    for col in _COLUMNS:
        if col.name in have:
            op.drop_column(_PIN, col.name)
