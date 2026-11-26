# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the project_governance module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.project_governance",
    entities=(
        Entity("GovernanceArea", label="data_paths.entity.governance_area"),
        Entity("GovernanceGate", label="data_paths.entity.governance_gate"),
        Entity("GovernanceModel", label="data_paths.entity.governance_model"),
        Entity("GovernanceChangeRequest", label="data_paths.entity.governance_change_request"),
    ),
    outputs=(
        DataPath(
            "oe_delivery_model",
            "DeliveryDecision",
            via="DeliveryDecision.governance_document_id",
            label="data_paths.entity.delivery_decision",
        ),
        DataPath("oe_economics", "Approval", via="Approval.governance_document_id", label="data_paths.entity.approval"),
        DataPath(
            "oe_engineering_brief",
            "EngineeringBrief",
            via="EngineeringBrief.governance_document_id",
            label="data_paths.entity.engineering_brief",
        ),
        DataPath(
            "oe_permits",
            "PermitRoadmap",
            via="PermitRoadmap.governance_document_id",
            label="data_paths.entity.permit_roadmap",
        ),
        DataPath(
            "oe_procurement_concept",
            "ProcurementConcept",
            via="ProcurementConcept.governance_document_id",
            label="data_paths.entity.procurement_concept",
        ),
        DataPath(
            "oe_staffing",
            "StaffingPlan",
            via="StaffingPlan.governance_document_id",
            label="data_paths.entity.staffing_plan",
        ),
    ),
)
