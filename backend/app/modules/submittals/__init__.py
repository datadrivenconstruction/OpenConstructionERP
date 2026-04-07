"""Submittals module.

Construction submittal management — shop drawings, product data, samples,
test reports, and certificates with multi-stage review/approval workflows.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.submittals.permissions import register_submittals_permissions

    register_submittals_permissions()
