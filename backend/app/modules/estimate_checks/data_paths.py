# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the estimate_checks module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.estimate_checks",
    entities=(
        Entity("EstimateCheckAcceptance", label="data_paths.entity.estimate_check_acceptance"),
        Entity("EstimateCheckSettings", label="data_paths.entity.estimate_check_settings"),
        Entity("EstimateCheckUserPref", label="data_paths.entity.estimate_check_user_pref"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, costs",
)
