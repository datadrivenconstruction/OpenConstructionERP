# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the rom_estimate module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.rom_estimate",
    entities=(Entity("RomEstimate", label="data_paths.entity.rom_estimate"),),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, costmodel",
)
