# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the ai_agents module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.ai_agents",
    entities=(
        Entity("AIFeedback", label="data_paths.entity.ai_feedback"),
        Entity("AgentDraft", label="data_paths.entity.agent_draft"),
        Entity("AgentRun", label="data_paths.entity.agent_run"),
        Entity("ProjectAgentGuard", label="data_paths.entity.project_agent_guard"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of ai, assemblies, boq, costmodel, costs, daily_diary and 8 more",
)
