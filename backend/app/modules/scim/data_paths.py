# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the scim module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.scim",
    entities=(Entity("ScimGroup", label="data_paths.entity.scim_group"),),
    reason="No foreign key joins its tables to another module's tables",
)
