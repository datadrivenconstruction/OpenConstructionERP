# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the construction_control module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Stale

DATA_PATHS = DataPaths(
    why="data_paths.why.construction_control",
    roles=(
        "inspector",
        "engineer",
        "site_manager",
        "surveyor",
    ),
    entities=(
        Entity("Inspection", label="data_paths.entity.inspection", route="/construction-control"),
        Entity("TestResult", label="data_paths.entity.test_result", route="/construction-control"),
        Entity("MaterialRecord", label="data_paths.entity.material_record", route="/construction-control"),
        Entity("AsBuiltRecord", label="data_paths.entity.asbuilt_record", route="/construction-control"),
        Entity("HoldGate", label="data_paths.entity.hold_gate", route="/construction-control"),
        Entity("HandoverPackage", label="data_paths.entity.handover_package", route="/construction-control"),
    ),
    inputs=(
        DataPath(
            "oe_procurement",
            "MaterialRecord",
            via="MaterialRecord.po_id",
            label="data_paths.entity.purchase_order",
            route="/procurement",
        ),
        DataPath(
            "oe_bim_hub",
            "ElementRef",
            via="ElementRef.model_id",
            label="data_paths.entity.bim_link",
            route="/bim",
        ),
        DataPath(
            "oe_schedule",
            "Inspection",
            via="Inspection.activity_id",
            label="data_paths.entity.activity",
            route="/schedule",
        ),
    ),
    outputs=(
        DataPath(
            "oe_ncr",
            "NCR",
            via="NCR.linked_inspection_id",
            label="data_paths.entity.ncr",
            route="/ncr",
            importance="high",
            breaks="data_paths.breaks.no_defect_trail",
        ),
    ),
    parameters=(
        Param(
            "AcceptanceCriterion.tolerance_upper",
            drives=(
                "AsBuiltRecord.tolerance_result",
                "TestResult.result",
                "oe_ncr:raised",
            ),
            label="data_paths.param.tolerance",
        ),
    ),
    stale=(
        Stale(
            source="AsBuiltRecord.updated_at",
            copy="AsBuiltRecord.validity_signed_at",
            label="data_paths.stale.changed_after_signing",
        ),
    ),
)
