# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bim_requirements module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity, External

DATA_PATHS = DataPaths(
    why="data_paths.why.bim_requirements",
    roles=(
        "engineer",
        "client",
    ),
    duties=(
        Duty("engineer", "data_paths.duty.bim_requirements.engineer"),
        Duty("client", "data_paths.duty.bim_requirements.client"),
    ),
    external=(External("file", "data_paths.external.requirement_files"),),
    entities=(
        Entity("BIMRequirementSet", label="data_paths.entity.requirement_set", route="/requirements"),
        Entity("BIMRequirement", label="data_paths.entity.requirement", route="/requirements"),
    ),
)
