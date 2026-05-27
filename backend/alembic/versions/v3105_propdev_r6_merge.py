# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3105 — property_dev R6 multi-head merge.

R6 shipped property_dev expansion in two parallel migration files:

    v3103_propdev_lead_reservation_spa_schedule_parties   (Lead/SPA pipeline)
    v3104_propdev_broker_escrow_pricematrix_hierarchy     (Broker/Escrow/PriceMatrix/Phase/Block)

Both branched off ``v3102_round5_merge`` so the two feature waves could
land in parallel worktrees without serialising. This file consolidates
the two heads into a single linear head so ``alembic upgrade head`` is
deterministic on fresh installs and the production VPS stays single-trunk.

Pure merge — no schema changes.

Revision ID: v3105_propdev_r6_merge
Revises: v3103_propdev_lead_reservation_spa_schedule_parties,
         v3104_propdev_broker_escrow_pricematrix_hierarchy
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "v3105_propdev_r6_merge"
down_revision: Union[str, Sequence[str], None] = (
    "v3103_propdev_lead_reservation_spa_schedule_parties",
    "v3104_propdev_broker_escrow_pricematrix_hierarchy",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Pure merge — no schema changes."""
    pass


def downgrade() -> None:
    """Pure merge — no schema changes."""
    pass
