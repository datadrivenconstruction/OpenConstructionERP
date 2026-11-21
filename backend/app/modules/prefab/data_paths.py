# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the prefab module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.prefab",
    roles=(
        "engineer",
        "site_manager",
        "quantity_surveyor",
    ),
    duties=(
        Duty("engineer", "data_paths.duty.prefab.engineer"),
        Duty("site_manager", "data_paths.duty.prefab.site_manager"),
        Duty("quantity_surveyor", "data_paths.duty.prefab.quantity_surveyor"),
    ),
    entities=(
        Entity("PrefabUnit", label="data_paths.entity.prefab_unit", route="/prefab"),
        Entity("ProductionEvent", label="data_paths.entity.production_event", route="/prefab"),
    ),
    inputs=(
        DataPath(
            "oe_boq",
            "Position",
            via="PrefabUnit.boq_position_id",
            label="data_paths.entity.position",
            route="/boq",
            importance="high",
            breaks="data_paths.breaks.no_prices",
        ),
        DataPath(
            "oe_assemblies",
            "Assembly",
            via="PrefabUnit.assembly_id",
            label="data_paths.entity.assembly",
            route="/assemblies",
        ),
    ),
)
