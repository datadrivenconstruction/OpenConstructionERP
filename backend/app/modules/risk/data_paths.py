# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the risk module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.risk",
    entities=(Entity("RiskItem", label="data_paths.entity.risk_item"),),
    reason="No foreign key joins its tables to another module's tables; subscribes to contracts.risk_register_update; publishes risk.assigned, risk.contingency.drawdown_confirmed, risk.contingency.drawdown_reversed, risk.escalated, risk.risk.created, risk.risk.deleted and 2 more; reads code of commitment_release, finance, project_governance",
)
