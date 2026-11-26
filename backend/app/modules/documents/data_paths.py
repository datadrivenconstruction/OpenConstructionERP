# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the documents module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.documents",
    entities=(
        Entity("Document", label="data_paths.entity.document"),
        Entity("DocumentFolder", label="data_paths.entity.document_folder"),
        Entity("FolderPermission", label="data_paths.entity.folder_permission"),
        Entity("ProjectPhoto", label="data_paths.entity.project_photo"),
    ),
    inputs=(
        DataPath(
            "oe_bim_hub", "DocumentBIMLink", via="DocumentBIMLink.bim_element_id", label="data_paths.entity.bim_element"
        ),
    ),
    outputs=(
        DataPath(
            "oe_compliance_docs",
            "ComplianceDoc",
            via="ComplianceDoc.attachment_document_id",
            label="data_paths.entity.compliance_doc",
        ),
        DataPath(
            "oe_costmodel",
            "CostForecastOverride",
            via="CostForecastOverride.document_id",
            label="data_paths.entity.cost_forecast_override",
        ),
        DataPath(
            "oe_leasing", "LeaseDocument", via="LeaseDocument.document_id", label="data_paths.entity.lease_document"
        ),
        DataPath("oe_photos", "PhotoAlbum", via="PhotoAlbum.cover_photo_id", label="data_paths.entity.photo_album"),
        DataPath(
            "oe_site_logistics",
            "ExpansionStage",
            via="ExpansionStage.plan_document_id",
            label="data_paths.entity.expansion_stage",
        ),
    ),
)
