# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the mcp module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.mcp",
    entities=(Entity("McpSettings", label="data_paths.entity.mcp_settings"),),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, documents, erp_chat, punchlist, rfi, schedule and 1 more",
)
