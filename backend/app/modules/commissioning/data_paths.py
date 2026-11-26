# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the commissioning module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.commissioning",
    entities=(
        Entity("CxSystem", label="data_paths.entity.cx_system"),
        Entity("CxChecklist", label="data_paths.entity.cx_checklist"),
        Entity("CxChecklistItem", label="data_paths.entity.cx_checklist_item"),
        Entity("CxIssue", label="data_paths.entity.cx_issue"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of project_governance, qms",
)
