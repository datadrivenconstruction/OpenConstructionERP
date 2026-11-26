# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the property_dev module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.property_dev",
    entities=(
        Entity("Development", label="data_paths.entity.development"),
        Entity("PropertyDevCustomTemplate", label="data_paths.entity.property_dev_custom_template"),
        Entity("PropertyDevHouseType", label="data_paths.entity.property_dev_house_type"),
        Entity("Broker", label="data_paths.entity.broker"),
    ),
    inputs=(DataPath("oe_contacts", "Buyer", via="Buyer.contact_id", label="data_paths.entity.contact"),),
)
