# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the connectors module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.connectors",
    entities=(Entity("ConnectorSource", label="data_paths.entity.connector_source"),),
    reason="No foreign key joins its tables to another module's tables; publishes documents.document.created; reads code of documents",
)
