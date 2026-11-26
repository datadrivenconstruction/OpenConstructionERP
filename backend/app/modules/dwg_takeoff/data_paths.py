# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the dwg_takeoff module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.dwg_takeoff",
    entities=(
        Entity("DwgDrawing", label="data_paths.entity.dwg_drawing"),
        Entity("DwgAnnotation", label="data_paths.entity.dwg_annotation"),
        Entity("DwgDrawingVersion", label="data_paths.entity.dwg_drawing_version"),
        Entity("DwgEntityGroup", label="data_paths.entity.dwg_entity_group"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to boq.position.deleted; reads code of boq, documents, takeoff, variations",
)
