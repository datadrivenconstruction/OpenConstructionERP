# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the clash_ai_triage module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.clash_ai_triage",
    entities=(Entity("ClashTriageResult", label="data_paths.entity.clash_triage_result"),),
    reason="No foreign key joins its tables to another module's tables; reads code of ai, clash",
)
