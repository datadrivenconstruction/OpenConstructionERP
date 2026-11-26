# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the leasing module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.leasing",
    entities=(
        Entity("Lease", label="data_paths.entity.lease"),
        Entity("LeaseEvent", label="data_paths.entity.lease_event"),
        Entity("RentScheduleLine", label="data_paths.entity.rent_schedule_line"),
        Entity("LeaseDocument", label="data_paths.entity.lease_document"),
    ),
    inputs=(
        DataPath("oe_documents", "LeaseDocument", via="LeaseDocument.document_id", label="data_paths.entity.document"),
    ),
)
