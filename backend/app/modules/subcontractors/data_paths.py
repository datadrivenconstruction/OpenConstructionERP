# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the subcontractors module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.subcontractors",
    entities=(
        Entity("SubcontractAgreement", label="data_paths.entity.subcontract_agreement"),
        Entity("SubcontractChange", label="data_paths.entity.subcontract_change"),
        Entity("LevyCatalogueItem", label="data_paths.entity.levy_catalogue_item"),
        Entity("SubcontractDocumentPolicy", label="data_paths.entity.subcontract_document_policy"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to contracts.contract.drafted_from_bid_award; publishes subcontractors.blocked, subcontractors.insurance.certificate_alert, subcontractors.insurance.expiring, subcontractors.payment.insurance_overridden, subcontractors.payment_application.excluded, subcontractors.payment_application.included and 8 more; reads code of bid_management, changeorders, contacts, contracts, doc_templates, finance and 4 more",
)
