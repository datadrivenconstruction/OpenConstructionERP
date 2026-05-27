# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3102 — Round 5 multi-head merge.

Round 5 introduced 10 module-scoped migrations across three parallel
revision tiers (v3099/v3100/v3101). Each module branched off v3098
independently to avoid serialising the per-module audit waves; the
post-chain head set looks like this:

    v3101_carbon   (from v3100_sched ← v3099_subm ← v3099_rfi ← v3099_eac)
    v3101_crm      (from v3100_sched)
    v3101_qms      (from v3100_sched)
    v3101_svc      (from v3100_sched)
    v3101_var      (from v3100_sched)

This file consolidates all five heads into a single linear head so
``alembic upgrade head`` is deterministic on fresh installs and the
production VPS stays single-trunk.

Pure merge — no schema changes.

Revision ID: v3102_round5_merge
Revises: (five Round-5 heads — see ``down_revision`` tuple)
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "v3102_round5_merge"
down_revision: Union[str, Sequence[str], None] = (
    "v3101_carbon",
    "v3101_crm",
    "v3101_qms",
    "v3101_svc",
    "v3101_var",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Pure merge — no schema changes."""
    pass


def downgrade() -> None:
    """Pure merge — no schema changes."""
    pass
