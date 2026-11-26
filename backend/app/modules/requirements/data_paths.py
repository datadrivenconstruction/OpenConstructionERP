# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the requirements module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.requirements",
    entities=(
        Entity("RequirementSet", label="data_paths.entity.requirement_set"),
        Entity("GateResult", label="data_paths.entity.gate_result"),
        Entity("Requirement", label="data_paths.entity.requirement"),
        Entity("RequirementDeliverable", label="data_paths.entity.requirement_deliverable"),
    ),
    inputs=(
        DataPath("oe_boq", "Requirement", via="Requirement.linked_position_id", label="data_paths.entity.position"),
    ),
    outputs=(
        DataPath(
            "oe_engineering_brief",
            "EngineeringBrief",
            via="EngineeringBrief.requirement_set_id",
            label="data_paths.entity.engineering_brief",
        ),
    ),
)
