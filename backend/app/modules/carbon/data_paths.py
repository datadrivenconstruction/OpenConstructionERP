# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the carbon module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.carbon",
    entities=(
        Entity("CarbonInventory", label="data_paths.entity.carbon_inventory"),
        Entity("CarbonTarget", label="data_paths.entity.carbon_target"),
        Entity("SustainabilityReport", label="data_paths.entity.sustainability_report"),
        Entity("CarbonCompanyActivity", label="data_paths.entity.carbon_company_activity"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes carbon.boq_position.assigned, carbon.budget.exceeded, carbon.company_report.generated, carbon.epd.imported, carbon.epd.ingested, carbon.inventory.auto_enriched and 4 more; reads code of bim_hub, boq, equipment, supplier_catalogs",
)
