# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""prefab - QR label, delivery note and element reference on an off-site unit.

Adds three nullable columns to ``oe_prefab_unit`` so a unit can be tracked
through the supply chain: ``qr_token`` (unique, printed as the QR label and
scanned on arrival), ``delivery_note_ref`` (the note it arrived with) and
``element_ref`` (the element it goes into, such as a pile mark). Existing
units get a token so they can be scanned too.

Idempotent. The downgrade drops the index and the columns.

Revision ID: v3332_prefab_supply_chain_tracking
Revises: v3340_procurement_profile_confirmation
Create Date: 2026-10-27
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3332_prefab_supply_chain_tracking"
down_revision: Union[str, Sequence[str], None] = "v3340_procurement_profile_confirmation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLE = "oe_prefab_unit"
_IX_QR = "ix_oe_prefab_unit_qr_token"
_COLUMNS = (("qr_token", 64), ("delivery_note_ref", 120), ("element_ref", 120))


def _columns(inspector: sa.engine.reflection.Inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        logger.info("v3332 prefab supply chain: table %s absent, skipping", _TABLE)
        return

    present = _columns(inspector)
    for name, length in _COLUMNS:
        if name not in present:
            op.add_column(_TABLE, sa.Column(name, sa.String(length), nullable=True))

    # One set-based UPDATE; both functions draw from a CSPRNG and need no extension.
    token = (
        "replace(gen_random_uuid()::text, '-', '')"
        if bind.dialect.name == "postgresql"
        else "lower(hex(randomblob(16)))"
    )
    # data-rewrite-ack: table=oe_prefab_unit growth=bounded rows=one row per off-site unit; backfills the new nullable qr_token column once
    issued = bind.execute(sa.text(f"UPDATE {_TABLE} SET qr_token = {token} WHERE qr_token IS NULL")).rowcount

    inspector = sa.inspect(bind)
    if not any(ix["name"] == _IX_QR for ix in inspector.get_indexes(_TABLE)):
        op.create_index(_IX_QR, _TABLE, ["qr_token"], unique=True)
    logger.info("v3332 prefab supply chain: schema ensured, %d tokens issued", issued)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    if any(ix["name"] == _IX_QR for ix in inspector.get_indexes(_TABLE)):
        op.drop_index(_IX_QR, table_name=_TABLE)
    present = _columns(inspector)
    for name, _length in reversed(_COLUMNS):
        if name in present:
            op.drop_column(_TABLE, name)
