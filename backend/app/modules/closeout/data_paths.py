# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the closeout module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.closeout",
    entities=(
        Entity("CloseoutPackage", label="data_paths.entity.closeout_package"),
        Entity("CloseoutDelivery", label="data_paths.entity.closeout_delivery"),
        Entity("CloseoutDossier", label="data_paths.entity.closeout_dossier"),
        Entity("CloseoutBinding", label="data_paths.entity.closeout_binding"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes closeout.package.issued; reads code of bim_hub, commissioning, defects_liability, documents, inspections, integrations and 2 more",
)
