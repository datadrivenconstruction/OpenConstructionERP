# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement scorecard / 3-way-match indices.

Wave 2 / T4 surfaces per-PO 3-way-match status (PO ↔ GR ↔ Invoice) and a
supplier scorecard. Both endpoints aggregate over goods receipts and POs:

* ``match_status`` joins ``oe_procurement_goods_receipt`` by ``po_id`` and
  filters on ``status='confirmed'`` to compute received quantities.
* ``supplier_scorecard`` filters POs by ``vendor_contact_id`` (one
  supplier may span dozens of POs over a year).

This migration adds two indices to keep both queries cheap on growing
tables:

* ``ix_oe_procurement_goods_receipt_po_status``  — composite
  (``po_id``, ``status``). Lets the GR aggregate use an index-only seek
  instead of a heap scan per PO.
* ``ix_oe_procurement_po_vendor_contact_id`` — single column on
  ``vendor_contact_id``. The ``vendor_contact_id`` column is plain (no
  prior index) so the scorecard otherwise full-scans the PO table.

Both creations are inspector-guarded and SQLite-safe (``create_index`` on
SQLite does not require ``batch_alter_table``).

Revision ID: v3084_procurement_scorecard_indices
Revises: v3083_merge_v311_heads
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3084_procurement_scorecard_indices"
down_revision: Union[str, Sequence[str], None] = "v3083_merge_v311_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GR_TABLE = "oe_procurement_goods_receipt"
_PO_TABLE = "oe_procurement_po"

_IX_GR_PO_STATUS = "ix_oe_procurement_goods_receipt_po_status"
_IX_PO_VENDOR = "ix_oe_procurement_po_vendor_contact_id"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    """Add scorecard / match-status supporting indices."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── GR composite (po_id, status) ─────────────────────────────────────
    if _has_table(inspector, _GR_TABLE) and not _has_index(inspector, _GR_TABLE, _IX_GR_PO_STATUS):
        try:
            op.create_index(
                _IX_GR_PO_STATUS,
                _GR_TABLE,
                ["po_id", "status"],
            )
        except Exception:  # noqa: BLE001 — idempotent guard
            pass

    # ── PO single-column vendor_contact_id ───────────────────────────────
    if _has_table(inspector, _PO_TABLE) and not _has_index(inspector, _PO_TABLE, _IX_PO_VENDOR):
        try:
            op.create_index(
                _IX_PO_VENDOR,
                _PO_TABLE,
                ["vendor_contact_id"],
            )
        except Exception:  # noqa: BLE001 — idempotent guard
            pass


def downgrade() -> None:
    """Drop the scorecard / match-status indices."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _PO_TABLE, _IX_PO_VENDOR):
        op.drop_index(_IX_PO_VENDOR, table_name=_PO_TABLE)

    if _has_index(inspector, _GR_TABLE, _IX_GR_PO_STATUS):
        op.drop_index(_IX_GR_PO_STATUS, table_name=_GR_TABLE)
