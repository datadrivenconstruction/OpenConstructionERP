# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the eac module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.eac",
    entities=(
        Entity("EacRuleset", label="data_paths.entity.eac_ruleset"),
        Entity("EacBlockGraph", label="data_paths.entity.eac_block_graph"),
        Entity("EacRule", label="data_paths.entity.eac_rule"),
        Entity("EacAliasSnapshot", label="data_paths.entity.eac_alias_snapshot"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes eac.run.cancelled, eac.run.rerun_started; reads code of bim_hub",
)
