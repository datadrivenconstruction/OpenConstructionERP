# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the delivery_model module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.delivery_model",
    entities=(
        Entity("ContractItem", label="data_paths.entity.contract_item"),
        Entity("ContractPackage", label="data_paths.entity.contract_package"),
        Entity("DecisionCriterion", label="data_paths.entity.decision_criterion"),
        Entity("DeliveryDecision", label="data_paths.entity.delivery_decision"),
    ),
    inputs=(
        DataPath(
            "oe_project_governance",
            "DeliveryDecision",
            via="DeliveryDecision.governance_document_id",
            label="data_paths.entity.governance_document",
        ),
    ),
)
