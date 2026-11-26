# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bim_hub module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.bim_hub",
    entities=(
        Entity("BIMFederation", label="data_paths.entity.bim_federation"),
        Entity("BIMModel", label="data_paths.entity.bim_model"),
        Entity("BIMQuantityMap", label="data_paths.entity.bim_quantity_map"),
        Entity("BIMElementGroup", label="data_paths.entity.bim_element_group"),
    ),
    outputs=(
        DataPath(
            "oe_construction_control",
            "ElementRef",
            via="ElementRef.bim_element_id",
            label="data_paths.entity.element_ref",
        ),
        DataPath(
            "oe_documents",
            "DocumentBIMLink",
            via="DocumentBIMLink.bim_element_id",
            label="data_paths.entity.document_bim_link",
        ),
    ),
)
