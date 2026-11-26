# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the offers module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.offers",
    entities=(
        Entity("Offer", label="data_paths.entity.offer"),
        Entity("OfferTextBlock", label="data_paths.entity.offer_text_block"),
        Entity("OfferSettings", label="data_paths.entity.offer_settings"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, contacts, contracts, doc_templates, estimate_basis",
)
