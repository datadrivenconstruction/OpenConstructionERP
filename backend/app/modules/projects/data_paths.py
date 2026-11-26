# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the projects module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.projects",
    entities=(
        Entity("MatchProjectSettings", label="data_paths.entity.match_project_settings"),
        Entity("ProjectMilestone", label="data_paths.entity.project_milestone"),
        Entity("ProjectModule", label="data_paths.entity.project_module"),
        Entity("ProjectProfile", label="data_paths.entity.project_profile"),
    ),
    outputs=(
        DataPath(
            "oe_accommodation", "Accommodation", via="Accommodation.project_id", label="data_paths.entity.accommodation"
        ),
        DataPath(
            "oe_ai_agents",
            "ProjectAgentSetting",
            via="ProjectAgentSetting.project_id",
            label="data_paths.entity.project_agent_setting",
        ),
        DataPath(
            "oe_ai_estimator",
            "AiEstimatorRun",
            via="AiEstimatorRun.project_id",
            label="data_paths.entity.ai_estimator_run",
        ),
        DataPath("oe_allowances", "Allowance", via="Allowance.project_id", label="data_paths.entity.allowance"),
        DataPath("oe_approval_routes", "Route", via="Route.project_id", label="data_paths.entity.route"),
        DataPath("oe_assemblies", "Assembly", via="Assembly.project_id", label="data_paths.entity.assembly"),
    ),
)
