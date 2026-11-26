# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the lessons_learned module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.lessons_learned",
    entities=(Entity("Lesson", label="data_paths.entity.lesson"),),
    reason="No foreign key joins its tables to another module's tables",
)
