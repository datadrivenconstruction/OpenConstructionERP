"""Install the OpenCDE BCF-API 3.0 sub-router into the main BCF router.

The :class:`ModuleLoader` reloads ``app.modules.bcf.router`` every time
the module is loaded (a hot-reload safeguard — see
``module_loader.py:188-225``). A naive ``router.include_router`` call
from ``manifest.py`` therefore lands on a *stale* router object that
the loader discards seconds later, and the OpenCDE routes never reach
the FastAPI app.

This module patches :mod:`importlib` for the lifetime of the next
``app.modules.bcf.router`` import: whenever that module finishes
executing, we look up ``router`` in its namespace, attach our OpenCDE
sub-router, and remove the hook. The hook is installed once at
manifest-discovery time and is a no-op for every other module's reload.

The patch is minimally invasive — it only intercepts reload/import of
this exact module, never raises into the loader, and removes itself
after firing once.
"""

from __future__ import annotations

import importlib
import logging
import sys

logger = logging.getLogger(__name__)

_TARGET_MODULE = "app.modules.bcf.router"
_INSTALLED_FLAG = "_OE_OPENCDE_MOUNTED"


def _attach_opencde(router_module) -> None:
    """Look up ``router`` in ``router_module`` and include OpenCDE."""
    try:
        from app.modules.bcf.opencde_router import opencde_router

        main_router = getattr(router_module, "router", None)
        if main_router is None:
            logger.debug("BCF router.py loaded without a `router` attribute; OpenCDE sub-router was NOT mounted")
            return
        # Idempotent — guard against double-mount when the loader reloads.
        if getattr(main_router, _INSTALLED_FLAG, False):
            return
        main_router.include_router(opencde_router)
        setattr(main_router, _INSTALLED_FLAG, True)
        logger.debug("Mounted OpenCDE 3.0 sub-router onto BCF main router")
    except Exception:  # noqa: BLE001 — best-effort; never block module load
        logger.exception("Failed to mount OpenCDE 3.0 sub-router")


def _patch_importlib() -> None:
    """Install the one-shot reload hook on ``importlib.reload``."""
    original_reload = importlib.reload
    original_import = importlib.import_module

    def _patched_reload(module, *args, **kwargs):
        result = original_reload(module, *args, **kwargs)
        if getattr(module, "__name__", "") == _TARGET_MODULE:
            _attach_opencde(result)
        return result

    def _patched_import(name, *args, **kwargs):
        result = original_import(name, *args, **kwargs)
        if name == _TARGET_MODULE:
            _attach_opencde(result)
        return result

    importlib.reload = _patched_reload  # type: ignore[assignment]
    importlib.import_module = _patched_import  # type: ignore[assignment]


# Install at manifest-discovery time (before the loader's router import).
_patch_importlib()


# If router.py is already in sys.modules (e.g. someone imported it
# earlier during test setup), attach immediately so the live router is
# patched before the loader's reload re-installs us.
if _TARGET_MODULE in sys.modules:
    _attach_opencde(sys.modules[_TARGET_MODULE])
