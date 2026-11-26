# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the site_logistics module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.site_logistics",
    entities=(
        Entity("CoordinationEntry", label="data_paths.entity.coordination_entry"),
        Entity("CustomsCase", label="data_paths.entity.customs_case"),
        Entity("ExpansionStage", label="data_paths.entity.expansion_stage"),
        Entity("Gate", label="data_paths.entity.gate"),
    ),
    inputs=(
        DataPath("oe_boq", "DeliveryLine", via="DeliveryLine.boq_position_id", label="data_paths.entity.position"),
        DataPath(
            "oe_documents", "ExpansionStage", via="ExpansionStage.plan_document_id", label="data_paths.entity.document"
        ),
    ),
)
