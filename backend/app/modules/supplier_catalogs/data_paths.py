# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the supplier_catalogs module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.supplier_catalogs",
    entities=(
        Entity("LegacyMigrationReport", label="data_paths.entity.legacy_migration_report"),
        Entity("PurchaseRequisition", label="data_paths.entity.purchase_requisition"),
        Entity("Warehouse", label="data_paths.entity.warehouse"),
        Entity("CatalogItemAttachment", label="data_paths.entity.catalog_item_attachment"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes bi_dashboards.kpi_recompute, match_elements.vector_reindex; reads code of boq, costs, documents",
)
