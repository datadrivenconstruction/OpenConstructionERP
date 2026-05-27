# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Merge the five /files-waves sibling branches into one head.

Each of W1+W2 (v3060), W3+W4 (v3061), W5+W10 (v3062), W6+W9 (v3063),
W7+W8 (v3064) was authored as a sibling branch of
``v3047_clash_severity_delta`` so the wave agents could run in parallel
without coordination. This empty migration consolidates all five into a
single head so ``alembic upgrade head`` resolves cleanly.

Revision ID: v3070_merge_files_waves
Revises: v3060_file_versions_trash, v3061_file_search_tags,
         v3062_file_savedviews_distribution,
         v3063_file_comments_references,
         v3064_file_transmittals_approvals
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "v3070_merge_files_waves"
down_revision: Union[str, Sequence[str], None] = (
    "v3060_file_versions_trash",
    "v3061_file_search_tags",
    "v3062_file_savedviews_distribution",
    "v3063_file_comments_references",
    "v3064_file_transmittals_approvals",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema changes — pure branch-consolidation marker."""


def downgrade() -> None:
    """Splits the chain back into five sibling heads — no schema changes."""
