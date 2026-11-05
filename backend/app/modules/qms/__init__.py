# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quality Management System (QMS) module.

Unified replacement for the legacy ``inspections``, ``ncr`` and
``punchlist`` modules with the addition of ITP (Inspection & Test Plan),
multi-signature inspection events, rolling punch lists, ISO 9001 style
audits, and a Cost of Poor Quality (COPQ) analytics endpoint.

Legacy modules continue to function in parallel - this module does not
delete or shadow them; cross-references are stored via metadata fields.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and event subscribers."""
    from app.modules.qms.events import register_subscribers
    from app.modules.qms.permissions import register_qms_permissions

    register_qms_permissions()
    register_subscribers()

    from app.modules.qms.validators import register_qms_validation_rules

    register_qms_validation_rules()
