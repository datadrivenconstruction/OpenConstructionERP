# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Final merge — consolidate the clash branch and the files-waves branch.

After the parallel clash + files work, two heads remained:

* ``v3049_clash_a4_intelligence`` — top of the clash collaboration tree
  (A2 / A3 / A4 deltas).
* ``v3070_merge_files_waves`` — top of the /files-waves tree (W1+W2,
  W3+W4, W5+W10, W6+W9, W7+W8).

This migration is empty; it only marks the merge point so
``alembic upgrade head`` resolves to a single revision.

Revision ID: v3071_merge_clash_and_files
Revises: v3049_clash_a4_intelligence, v3070_merge_files_waves
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "v3071_merge_clash_and_files"
down_revision: Union[str, Sequence[str], None] = (
    "v3049_clash_a4_intelligence",
    "v3070_merge_files_waves",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema changes — pure branch-consolidation marker."""


def downgrade() -> None:
    """Splits the chain back into two heads — no schema changes."""
