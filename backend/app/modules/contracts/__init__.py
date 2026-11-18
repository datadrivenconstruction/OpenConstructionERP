# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts module - Contract Types Engine.

Multi-type contract engine supporting lump-sum, GMP, cost-plus, T&M,
unit-price, design-build, and combinations. Manages contract values,
schedule of values (SoV), progress claims, retention, gainshare,
liquidated damages, and final accounts.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.contracts.permissions import register_contracts_permissions
    from app.modules.contracts.validators import register_contracts_validation_rules

    register_contracts_permissions()
    register_contracts_validation_rules()

    from app.core.doc_templates.layout.spec import register_layout_provider
    from app.modules.contracts.layouts import register_contract_layouts

    register_layout_provider(register_contract_layouts)
