# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the cost_recovery module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.cost_recovery",
    entities=(
        Entity("BackCharge", label="data_paths.entity.back_charge"),
        Entity("BackChargeApportionment", label="data_paths.entity.back_charge_apportionment"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes cost.back_charge.recorded; reads code of claims_evidence, contacts, ncr, punchlist, subcontractors",
)
