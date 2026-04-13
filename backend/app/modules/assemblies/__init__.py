"""Assemblies & Calculations module.

Provides composite cost items (assemblies / calculations) built from
cost database entries with factors. Supports templates, regional factors,
cloning, and integration with the BOQ module.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions and event subscribers."""
    from app.modules.assemblies.events import register_assemblies_subscribers
    from app.modules.assemblies.permissions import register_assemblies_permissions

    register_assemblies_permissions()
    register_assemblies_subscribers()
