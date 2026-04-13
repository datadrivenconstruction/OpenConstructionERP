"""DWG Takeoff module.

Provides 2D DWG/DXF drawing viewer with measurements, annotations,
and BOQ linking for construction quantity takeoff workflows.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.dwg_takeoff.permissions import register_dwg_takeoff_permissions

    register_dwg_takeoff_permissions()
