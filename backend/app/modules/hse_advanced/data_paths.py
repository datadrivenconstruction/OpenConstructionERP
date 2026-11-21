# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the hse_advanced module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.hse_advanced",
    roles=(
        "site_manager",
        "engineer",
        "inspector",
    ),
    duties=(
        Duty("site_manager", "data_paths.duty.hse_advanced.site_manager"),
        Duty("engineer", "data_paths.duty.hse_advanced.engineer"),
        Duty("inspector", "data_paths.duty.hse_advanced.inspector"),
    ),
    entities=(
        Entity("PermitToWork", label="data_paths.entity.permit_to_work", route="/hse-advanced"),
        Entity("JobSafetyAnalysis", label="data_paths.entity.job_safety_analysis", route="/hse-advanced"),
        Entity("ToolboxTalk", label="data_paths.entity.toolbox_talk", route="/hse-advanced"),
        Entity("SafetyAudit", label="data_paths.entity.safety_audit", route="/hse-advanced"),
        Entity("CorrectiveAction", label="data_paths.entity.corrective_action", route="/hse-advanced"),
    ),
    inputs=(
        DataPath(
            "oe_safety",
            "CorrectiveAction",
            via="CorrectiveAction.source_ref",
            label="data_paths.entity.safety_incident",
            importance="high",
            breaks="data_paths.breaks.action_without_incident",
            where=(Where("source_type", "eq", "incident"),),
        ),
    ),
)
