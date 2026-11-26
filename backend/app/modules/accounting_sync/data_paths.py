# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the accounting_sync module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.accounting_sync",
    entities=(
        Entity("SyncLogEntry", label="data_paths.entity.sync_log_entry"),
        Entity("AccountingConnection", label="data_paths.entity.accounting_connection"),
        Entity("AccountMapping", label="data_paths.entity.account_mapping"),
        Entity("ExternalRef", label="data_paths.entity.external_ref"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes accounting_sync.sync.failed; reads code of contacts, finance, guarantees, notifications, payroll",
)
