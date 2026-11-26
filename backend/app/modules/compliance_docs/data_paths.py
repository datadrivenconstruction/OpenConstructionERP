# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the compliance_docs module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.compliance_docs",
    entities=(Entity("ComplianceDoc", label="data_paths.entity.compliance_doc"),),
    inputs=(
        DataPath(
            "oe_documents",
            "ComplianceDoc",
            via="ComplianceDoc.attachment_document_id",
            label="data_paths.entity.document",
        ),
    ),
)
