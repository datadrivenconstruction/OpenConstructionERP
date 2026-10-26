# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractor Management module.

Manages the subcontractor lifecycle: prequalification, certificates,
agreements, work packages, payment applications, retention, and rating.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions, the claim rollup rules and their data."""
    from app.modules.subcontractors.claim_rules import register_sub_rollup_context, register_sub_rollup_rules
    from app.modules.subcontractors.permissions import register_subcontractors_permissions

    register_subcontractors_permissions()
    # The subcontract checks join the contracts module's pay_application set,
    # so submitting a GC claim that bills sub work also checks the sub paper.
    register_sub_rollup_rules()
    # And the rollup those checks read is handed to contracts from here,
    # because contracts must not import a module an install may not have.
    register_sub_rollup_context()
    from app.modules.subcontractors.insurance_rules import register_insurance_rules

    register_insurance_rules()
