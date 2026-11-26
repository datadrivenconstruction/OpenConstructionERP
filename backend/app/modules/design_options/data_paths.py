# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the design_options module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.design_options",
    entities=(
        Entity("DesignOptionSet", label="data_paths.entity.design_option_set"),
        Entity("DesignOption", label="data_paths.entity.design_option"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of bim_hub, boq, carbon, documents, match_elements, schedule",
)
