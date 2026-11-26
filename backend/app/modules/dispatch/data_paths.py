# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the dispatch module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.dispatch",
    entities=(
        Entity("DispatchLocation", label="data_paths.entity.dispatch_location"),
        Entity("DispatchCrew", label="data_paths.entity.dispatch_crew"),
        Entity("DispatchViewPref", label="data_paths.entity.dispatch_view_pref"),
        Entity("DispatchPlacement", label="data_paths.entity.dispatch_placement"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of equipment, field_time, notifications, resources",
)
