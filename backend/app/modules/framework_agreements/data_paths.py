# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the framework_agreements module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.framework_agreements",
    entities=(
        Entity("FrameworkAdjustment", label="data_paths.entity.framework_adjustment"),
        Entity("FrameworkRateItem", label="data_paths.entity.framework_rate_item"),
        Entity("FrameworkRatePeriod", label="data_paths.entity.framework_rate_period"),
    ),
    inputs=(
        DataPath(
            "oe_contracts",
            "FrameworkRateItem",
            via="FrameworkRateItem.agreement_id",
            label="data_paths.entity.contract",
        ),
    ),
)
