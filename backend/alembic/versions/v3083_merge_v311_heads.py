# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Merge the three v3.11 sibling heads.

After parallel work three migrations branched off ``v3071_merge_clash_and_files``:

* ``v3080_risk_pert_columns``            — Risk Register Monte Carlo (PERT) cols.
* ``v3081_punchlist_reopen_audit``       — Punch List reopen audit trail.
* ``v3082_changeorders_approval_chain``  — Procore-style multi-step approval
  chain + commitment / RFI links on change orders.

This revision is empty; it only marks the merge point so ``alembic
upgrade head`` resolves to a single revision.

Revision ID: v3083_merge_v311_heads
Revises: v3080_risk_pert_columns, v3081_punchlist_reopen_audit, v3082_changeorders_approval_chain
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "v3083_merge_v311_heads"
down_revision: Union[str, Sequence[str], None] = (
    "v3080_risk_pert_columns",
    "v3081_punchlist_reopen_audit",
    "v3082_changeorders_approval_chain",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema changes — pure branch-consolidation marker."""


def downgrade() -> None:
    """Splits the chain back into three heads — no schema changes."""
