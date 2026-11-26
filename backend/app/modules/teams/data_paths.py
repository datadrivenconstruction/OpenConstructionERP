# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the teams module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.teams",
    entities=(
        Entity("Team", label="data_paths.entity.team"),
        Entity("RosterMember", label="data_paths.entity.roster_member"),
        Entity("EntityVisibility", label="data_paths.entity.entity_visibility"),
        Entity("TeamMembership", label="data_paths.entity.team_membership"),
    ),
    outputs=(
        DataPath("oe_saved_views", "SavedView", via="SavedView.shared_team_id", label="data_paths.entity.saved_view"),
    ),
)
