# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""tendering package header and the issuing company; signatory and bank on legal entities.

Adds to ``oe_tendering_package`` the company the package is bought for
(``legal_entity_id``), trade, cost line, four dates (issue, questions until,
bids due, award planned) and four roles (buyer, estimator, site manager,
approver). Adds ``default_signatory``, ``bank`` and ``logo_data_url`` to
``oe_legal_entities_entity``. Every column is nullable and additive; a running
install also gets them from the auto-migrator. Each step is guarded, so a
re-run changes nothing.

Revision ID: awe01_award_entities
Revises: vcrm01_deal_activities
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "awe01_award_entities"
down_revision: Union[str, Sequence[str], None] = "vcrm01_deal_activities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PKG = "oe_tendering_package"
_ENT = "oe_legal_entities_entity"

# GUID columns are VARCHAR(36), as the ORM type renders them.
_PKG_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("legal_entity_id", sa.String(36)),
    ("trade", sa.String(120)),
    ("cost_line_id", sa.String(36)),
    ("issue_date", sa.Date()),
    ("questions_until", sa.Date()),
    ("bids_due", sa.Date()),
    ("award_planned", sa.Date()),
    ("buyer_id", sa.String(36)),
    ("estimator_id", sa.String(36)),
    ("site_manager_id", sa.String(36)),
    ("approver_id", sa.String(36)),
)
_PKG_INDEXED = ("legal_entity_id", "cost_line_id")
_ENT_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("default_signatory", sa.String(255)),
    ("bank", sa.JSON()),
    ("logo_data_url", sa.Text()),
)


def _columns(insp: sa.Inspector, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Add the header columns and the entity's signatory and bank."""
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if _PKG in tables:
        have = _columns(insp, _PKG)
        indexes = {i["name"] for i in insp.get_indexes(_PKG)}
        for name, type_ in _PKG_COLUMNS:
            if name not in have:
                op.add_column(_PKG, sa.Column(name, type_, nullable=True))
        for name in _PKG_INDEXED:
            ix = f"ix_{_PKG}_{name}"
            if ix not in indexes:
                op.create_index(op.f(ix), _PKG, [name])
    if _ENT in tables:
        have = _columns(insp, _ENT)
        for name, type_ in _ENT_COLUMNS:
            if name not in have:
                op.add_column(_ENT, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    """Drop what upgrade added."""
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if _PKG in tables:
        have = _columns(insp, _PKG)
        indexes = {i["name"] for i in insp.get_indexes(_PKG)}
        for name in _PKG_INDEXED:
            ix = f"ix_{_PKG}_{name}"
            if ix in indexes:
                op.drop_index(op.f(ix), table_name=_PKG)
        for name, _type in _PKG_COLUMNS:
            if name in have:
                op.drop_column(_PKG, name)
    if _ENT in tables:
        have = _columns(insp, _ENT)
        for name, _type in _ENT_COLUMNS:
            if name in have:
                op.drop_column(_ENT, name)
