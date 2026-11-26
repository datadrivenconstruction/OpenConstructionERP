# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the service_charges module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.service_charges",
    entities=(
        Entity("OwnersAssociation", label="data_paths.entity.owners_association"),
        Entity("ApportionmentKey", label="data_paths.entity.apportionment_key"),
        Entity("ChargeBudget", label="data_paths.entity.charge_budget"),
        Entity("ChargeDemand", label="data_paths.entity.charge_demand"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of finance, legal_entities, service",
)
