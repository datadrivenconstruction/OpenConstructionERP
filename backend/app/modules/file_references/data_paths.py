# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_references module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_references",
    roles=(
        "project_manager",
        "engineer",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.file_references.project_manager"),
        Duty("engineer", "data_paths.duty.file_references.engineer"),
    ),
    entities=(
        Entity("FileReference", label="data_paths.entity.file_reference", route="/files"),
        Entity("FileNamingViolation", label="data_paths.entity.naming_violation", route="/files"),
    ),
)
