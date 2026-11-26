# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the plant_register module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.plant_register",
    entities=(
        Entity("ItService", label="data_paths.entity.it_service"),
        Entity("PlantItem", label="data_paths.entity.plant_item"),
        Entity("PlantSettings", label="data_paths.entity.plant_settings"),
        Entity("DecisionPaper", label="data_paths.entity.decision_paper"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes plant.item.created, plant.item.state_changed, plant.item.updated, plant.order.due_soon, plant.order.overdue, plant.paper.approved and 1 more; reads code of approval_routes, boq, cde, commissioning, contacts, notifications and 7 more",
)
