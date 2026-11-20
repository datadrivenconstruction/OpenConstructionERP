"""Design module: the ERP side of contract ddc-erp-link/1 (see contract/README.md)."""


async def on_startup() -> None:
    from .brief_api import register_tool
    from .permissions import register_design_permissions
    from .validators import register_design_rules

    register_design_permissions()
    register_design_rules()
    register_tool()
    try:  # the job queue is core; a missing one only disables generation
        from . import jobs

        jobs.register_handler()
    except ImportError:
        pass
    try:
        from .mcp_actions import register_specs
    except ImportError:  # the assistant module is not installed: no proposals, no MCP tools
        return
    register_specs()
