# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the portal module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.portal",
    entities=(
        Entity("PortalUser", label="data_paths.entity.portal_user"),
        Entity("PortalAccessRule", label="data_paths.entity.portal_access_rule"),
        Entity("PortalDocumentAccessLog", label="data_paths.entity.portal_document_access_log"),
        Entity("PortalMagicLink", label="data_paths.entity.portal_magic_link"),
    ),
    inputs=(DataPath("oe_contacts", "PortalUser", via="PortalUser.contact_id", label="data_paths.entity.contact"),),
)
