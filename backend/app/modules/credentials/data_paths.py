# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the credentials module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.credentials",
    entities=(
        Entity("Credential", label="data_paths.entity.credential"),
        Entity("CredentialRequirement", label="data_paths.entity.credential_requirement"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes credentials.expiry.alert; reads code of approval_routes, compliance_docs",
)
