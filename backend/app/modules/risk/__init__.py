# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk Register module.

Tracks project risks with probability/impact assessment, mitigation strategies,
and provides risk matrix visualization data.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.risk.permissions import register_risk_permissions

    register_risk_permissions()
    from app.modules.risk.validators import register_risk_validation_rules

    register_risk_validation_rules()
    from app.modules.risk.evidence import register_gate_evidence

    register_gate_evidence()
