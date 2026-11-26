# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the quality_concept module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.quality_concept",
    entities=(
        Entity("AcceptanceUnit", label="data_paths.entity.acceptance_unit"),
        Entity("AppliedStandard", label="data_paths.entity.applied_standard"),
        Entity("CertificationTarget", label="data_paths.entity.certification_target"),
        Entity("CommissioningStageDef", label="data_paths.entity.commissioning_stage_def"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to cc.gate.released, cc.handover.issued, cc.handover.revoked, project_governance.frame_document.state_changed; publishes acceptance.accepted, acceptance.requested, acceptance.revoked, concept.binding, concept.reopened, concept.submitted and 3 more; reads code of cde, closeout, commissioning, construction_control, contacts, daily_diary and 10 more",
)
