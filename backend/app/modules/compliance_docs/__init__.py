# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Compliance documents tracker - insurance / permits / bonds / certifications.

Lightweight project-scoped module for tracking documents that expire
(insurance policies, building / electrical / plumbing permits, payment /
performance / bid bonds, safety certifications, etc.) with automatic
status derivation (active → expiring_soon → expired) and a convenience
"expiring soon" endpoint for the dashboard widget.

This module is intentionally separate from the ``compliance`` (DSL rule
authoring) module - the two share no data and have very different
lifecycles.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.compliance_docs.permissions import (
        register_compliance_docs_permissions,
    )

    register_compliance_docs_permissions()

    from app.modules.compliance_docs.validators import register_compliance_docs_validation_rules

    register_compliance_docs_validation_rules()
