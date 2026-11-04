# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Correspondence module.

Project correspondence tracking - letters, emails, notices, memos and
reports with direction tracking, contact linking, and document
cross-references.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.correspondence.permissions import register_correspondence_permissions

    register_correspondence_permissions()
    from app.modules.correspondence.validators import register_correspondence_validation_rules

    register_correspondence_validation_rules()
