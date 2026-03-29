"""Risk Register module.

Tracks project risks with probability/impact assessment, mitigation strategies,
and provides risk matrix visualization data.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.risk.permissions import register_risk_permissions

    register_risk_permissions()
