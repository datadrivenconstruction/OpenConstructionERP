# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team Standup - one page a PM team stands around each morning.

Each person posts one entry per day (where they are, what happened
yesterday, what today holds, what is blocking them); everyone reads the
same board and can comment on each other's entries. Deliberately
team-level rather than project-level: the roster is whoever has been
posting lately, not a configured list.
"""

# Team metrics ride along without touching router.py / models.py:
#
# * ``presence_models`` joins Base.metadata here because the module
#   loader imports this package BEFORE ``models.py``, so the startup
#   auto-create (and the test template) see the presence table.
# * The loader only ever mounts ``router.router``; including the metrics
#   router INTO it here (at package import, i.e. before the loader reads
#   the attribute) is what puts /presence/ping and /metrics on the API.
#   ``router.py`` imports this package's submodules, which Python resolves
#   fine mid-init, so the import below is not circular.
from app.modules.team_standup import presence_models as _presence_models  # noqa: E402,F401


def _mount_metrics_router() -> None:
    from app.modules.team_standup import metrics_router as _metrics
    from app.modules.team_standup import router as _router_mod

    already = {getattr(r, "path", "") for r in _router_mod.router.routes}
    if "/metrics" not in already:
        _router_mod.router.include_router(_metrics.router)


_mount_metrics_router()
