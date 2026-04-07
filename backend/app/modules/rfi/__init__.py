"""RFI module.

Request for Information management — questions from contractors to designers/consultants
with response tracking, cost/schedule impact assessment, and drawing links.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.rfi.permissions import register_rfi_permissions

    register_rfi_permissions()
