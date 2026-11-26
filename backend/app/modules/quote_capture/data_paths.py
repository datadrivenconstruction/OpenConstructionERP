# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the quote_capture module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.quote_capture",
    entities=(Entity("CapturedQuote", label="data_paths.entity.captured_quote"),),
    reason="No foreign key joins its tables to another module's tables; reads code of ai, boq, procurement, supplier_catalogs, tendering",
)
