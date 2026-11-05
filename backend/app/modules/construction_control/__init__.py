# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Construction-control module.

The universal QA/QC engine: acceptance criteria, inspections with a phase discriminator
(MIR / WIR / IR / hidden-works / acceptance), material records (digital passport),
lab test results, as-built records (verified survey/scan records with a signed
legal-record attestation), hold/witness/surveillance/review gating, and handover /
acceptance packages (regime-aware completion with auto-assembled acceptance evidence, a
completion gate over open NCRs and unreleased hold points, and an e-signed acceptance
certificate), all with format-agnostic model linking through the Universal Element
Reference, where a failed check raises a non-conformance report automatically.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.construction_control.permissions import register_construction_control_permissions

    register_construction_control_permissions()
    from app.modules.construction_control.validators import register_construction_control_validation_rules

    register_construction_control_validation_rules()
