# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the formwork module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.formwork",
    entities=(
        Entity("FormworkAssignment", label="data_paths.entity.formwork_assignment"),
        Entity("FormworkScheduleLine", label="data_paths.entity.formwork_schedule_line"),
        Entity("FormworkSystem", label="data_paths.entity.formwork_system"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq",
)
