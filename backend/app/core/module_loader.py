"""Module loader​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ — discovers, loads, and manages business modules.

Each module is a Python package under app/modules/ with a manifest.py.
The loader handles dependency resolution, lifecycle, and route mounting.

Module lifecycle:
    1. Discovery: scan app/modules/ for manifest.py files
    2. Resolution: topological sort by dependencies
    3. Loading: import module, register models, hooks, events
    4. Mounting: attach router to FastAPI app
    5. Startup: call module.on_startup() if defined
"""

import contextlib
import importlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)

MODULES_DIR = Path(__file__).parent.parent / "modules"


@dataclass
class ModuleManifest:
    """Metadata for a module. Defined in each module's manifest.py."""

    name: str  # Unique module name, e.g. "oe_boq"
    version: str  # SemVer, e.g. "1.0.0"
    display_name: str  # Human-readable name
    description: str = ""
    author: str = ""
    category: str = "core"  # "core", "integration", "regional", "community"
    depends: list[str] = field(default_factory=list)
    optional_depends: list[str] = field(default_factory=list)
    display_name_i18n: dict[str, str] = field(default_factory=dict)  # {"de": "...", "ru": "..."}
    auto_install: bool = False
    enabled: bool = True


@dataclass
class LoadedModule:
    """A module that has been loaded into the application."""

    manifest: ModuleManifest
    package: Any  # The imported Python package
    router: Any | None = None
    models: list[Any] = field(default_factory=list)


class ModuleLoader:
    """Discovers, resolves, and loads modules."""

    def __init__(self) -> None:
        self._manifests: dict[str, ModuleManifest] = {}
        self._modules: dict[str, LoadedModule] = {}
        self._load_order: list[str] = []
        self._disabled: set[str] = set()  # modules disabled via state persistence

    @property
    def loaded_modules(self) -> dict[str, LoadedModule]:
        return self._modules

    def discover(self, modules_dir: Path | None = None) -> list[ModuleManifest]:
        """Scan modules directory for manifest.py files."""
        scan_dir = modules_dir or MODULES_DIR
        manifests: list[ModuleManifest] = []

        if not scan_dir.exists():
            logger.warning("Modules directory not found: %s", scan_dir)
            return manifests

        for module_dir in sorted(scan_dir.iterdir()):
            if not module_dir.is_dir():
                continue
            if module_dir.name.startswith("_"):
                continue

            manifest_file = module_dir / "manifest.py"
            if not manifest_file.exists():
                continue

            try:
                module_path = f"app.modules.{module_dir.name}.manifest"
                mod = importlib.import_module(module_path)
                manifest = getattr(mod, "manifest", None)
                if isinstance(manifest, ModuleManifest):
                    self._manifests[manifest.name] = manifest
                    manifests.append(manifest)
                    logger.info(
                        "Discovered module: %s v%s (%s)",
                        manifest.name,
                        manifest.version,
                        manifest.display_name,
                    )
                else:
                    logger.warning("No valid manifest in %s", module_dir.name)
            except Exception:
                logger.exception("Failed to load manifest from %s", module_dir.name)

        return manifests

    def resolve_order(self) -> list[str]:
        """Topological sort of modules by dependencies."""
        resolved: list[str] = []
        seen: set[str] = set()
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in resolved:
                return
            if name in visiting:
                raise ValueError(f"Circular dependency detected involving: {name}")
            if name not in self._manifests:
                logger.warning("Unknown dependency: %s", name)
                return

            visiting.add(name)
            manifest = self._manifests[name]
            for dep in manifest.depends:
                visit(dep)
            visiting.discard(name)
            seen.add(name)
            resolved.append(name)

        for name, manifest in self._manifests.items():
            if manifest.enabled:
                visit(name)

        self._load_order = resolved
        return resolved

    async def load_all(self, app: FastAPI) -> None:
        """Discover, resolve, and load all modules.

        Reads persisted module states to skip disabled non-core modules.
        """
        from app.core.module_state import load_module_states

        self.discover()

        # Apply persisted states: mark non-core modules as disabled
        states = load_module_states()
        for name, state in states.items():
            if name in self._manifests and not state.enabled:
                manifest = self._manifests[name]
                if manifest.category != "core":
                    manifest.enabled = False
                    self._disabled.add(name)
                    logger.info("Module %s is disabled by persisted state", name)

        order = self.resolve_order()

        logger.info("Loading %d modules in order: %s", len(order), order)

        for module_name in order:
            try:
                await self._load_module(module_name, app)
            except Exception:
                logger.exception("Failed to load module: %s", module_name)
                raise

        logger.info("All modules loaded successfully")

    async def _load_module(self, module_name: str, app: FastAPI) -> None:
        """Load a single module."""
        manifest = self._manifests[module_name]

        # Determine the package directory name (oe_boq → boq if using oe_ prefix)
        # Convention: module directory name = manifest.name without oe_ prefix
        dir_name = module_name.removeprefix("oe_")
        package_path = f"app.modules.{dir_name}"

        try:
            package = importlib.import_module(package_path)
        except ModuleNotFoundError:
            # Try with full name
            package_path = f"app.modules.{module_name}"
            package = importlib.import_module(package_path)

        loaded = LoadedModule(manifest=manifest, package=package)

        # Load router if exists
        try:
            router_module_name = f"{package_path}.router"
            # Clear stale import cache entry (handles hot-reload after new files added)
            if router_module_name in sys.modules:
                importlib.reload(sys.modules[router_module_name])
                router_mod = sys.modules[router_module_name]
            else:
                router_mod = importlib.import_module(router_module_name)
            router = getattr(router_mod, "router", None)
            if router:
                prefix = f"/api/v1/{dir_name}"
                app.include_router(router, prefix=prefix, tags=[manifest.display_name])
                loaded.router = router
                logger.info("Mounted router for %s at %s", module_name, prefix)
        except ModuleNotFoundError:
            logger.debug("No router for module %s", module_name)

        # Load models (for Alembic discovery)
        try:
            models_mod = importlib.import_module(f"{package_path}.models")
            loaded.models = [models_mod]
        except ModuleNotFoundError:
            pass

        # Load hooks
        with contextlib.suppress(ModuleNotFoundError):
            importlib.import_module(f"{package_path}.hooks")

        # Load events
        with contextlib.suppress(ModuleNotFoundError):
            importlib.import_module(f"{package_path}.events")

        # Load validators
        with contextlib.suppress(ModuleNotFoundError):
            importlib.import_module(f"{package_path}.validators")

        # Call on_startup if defined
        startup = getattr(package, "on_startup", None)
        if callable(startup):
            await startup()

        self._modules[module_name] = loaded
        logger.info("Loaded module: %s v%s", module_name, manifest.version)

    def get_module(self, name: str) -> LoadedModule | None:
        return self._modules.get(name)

    def list_modules(self) -> list[dict[str, Any]]:
        """List all discovered modules with enabled/disabled/loaded status."""
        result: list[dict[str, Any]] = []

        for name, manifest in self._manifests.items():
            loaded = name in self._modules
            loaded_mod = self._modules.get(name)
            result.append({
                "name": manifest.name,
                "version": manifest.version,
                "display_name": manifest.display_name,
                "display_name_i18n": manifest.display_name_i18n,
                "description": manifest.description,
                "author": manifest.author,
                "category": manifest.category,
                "depends": manifest.depends,
                "optional_depends": manifest.optional_depends,
                "has_router": loaded_mod.router is not None if loaded_mod else False,
                "loaded": loaded,
                "enabled": name not in self._disabled,
                "is_core": manifest.category == "core",
            })

        return result

    # ── Runtime enable / disable ─────────────────────────────────────────

    def is_enabled(self, module_name: str) -> bool:
        """Check if module is enabled (considers state persistence)."""
        if module_name not in self._manifests:
            return False
        return module_name not in self._disabled

    async def enable_module(self, module_name: str, app: FastAPI) -> dict[str, Any]:
        """Enable a disabled module at runtime (loads router, models).

        Also loads any unloaded dependencies required by this module.

        Returns:
            dict with module info after enabling.

        Raises:
            ValueError: If module_name is unknown.
        """
        from app.core.module_state import set_module_enabled as persist_enable

        if module_name not in self._manifests:
            raise ValueError(f"Unknown module: {module_name}")

        manifest = self._manifests[module_name]

        # Already enabled and loaded
        if module_name in self._modules and module_name not in self._disabled:
            return {"name": module_name, "status": "already_enabled"}

        # Ensure required dependencies are loaded first
        for dep in manifest.depends:
            if dep not in self._modules:
                if dep in self._manifests:
                    await self.enable_module(dep, app)
                else:
                    logger.warning("Missing dependency %s for %s", dep, module_name)

        # Update state
        manifest.enabled = True
        self._disabled.discard(module_name)

        # Load if not already loaded
        if module_name not in self._modules:
            await self._load_module(module_name, app)

        # Persist
        core_names = {n for n, m in self._manifests.items() if m.category == "core"}
        persist_enable(module_name, True, core_modules=core_names)

        return {
            "name": module_name,
            "status": "enabled",
            "display_name": manifest.display_name,
            "version": manifest.version,
        }

    async def disable_module(self, module_name: str, app: FastAPI) -> dict[str, Any]:
        """Disable a module at runtime (removes router from app).

        Core modules cannot be disabled.

        Returns:
            dict with module info after disabling.

        Raises:
            ValueError: If module is core or if other enabled modules depend on it.
        """
        from app.core.module_state import set_module_enabled as persist_enable

        if module_name not in self._manifests:
            raise ValueError(f"Unknown module: {module_name}")

        manifest = self._manifests[module_name]

        if manifest.category == "core":
            raise ValueError(
                f"Module '{module_name}' is a core module and cannot be disabled."
            )

        # Check that no other enabled module depends on this one
        tree = self.get_dependency_tree(module_name)
        dependents = tree.get("dependents", [])
        enabled_dependents = [
            d for d in dependents if d not in self._disabled
        ]
        if enabled_dependents:
            raise ValueError(
                f"Cannot disable '{module_name}': required by enabled modules: "
                f"{', '.join(enabled_dependents)}"
            )

        # Remove router from the FastAPI app
        loaded = self._modules.get(module_name)
        if loaded and loaded.router:
            dir_name = module_name.removeprefix("oe_")
            prefix = f"/api/v1/{dir_name}"
            app.routes[:] = [
                r for r in app.routes
                if not (hasattr(r, "path") and getattr(r, "path", "").startswith(prefix))
            ]
            logger.info("Removed routes for %s (prefix %s)", module_name, prefix)

        # Mark as disabled
        manifest.enabled = False
        self._disabled.add(module_name)

        # Persist
        core_names = {n for n, m in self._manifests.items() if m.category == "core"}
        persist_enable(module_name, False, core_modules=core_names)

        return {
            "name": module_name,
            "status": "disabled",
            "display_name": manifest.display_name,
        }

    def get_module_info(self, name: str) -> dict[str, Any]:
        """Detailed module info including dependencies, state, routes."""
        if name not in self._manifests:
            raise ValueError(f"Unknown module: {name}")

        manifest = self._manifests[name]
        loaded = self._modules.get(name)
        dir_name = name.removeprefix("oe_")

        return {
            "name": manifest.name,
            "version": manifest.version,
            "display_name": manifest.display_name,
            "display_name_i18n": manifest.display_name_i18n,
            "description": manifest.description,
            "author": manifest.author,
            "category": manifest.category,
            "depends": manifest.depends,
            "optional_depends": manifest.optional_depends,
            "auto_install": manifest.auto_install,
            "is_core": manifest.category == "core",
            "enabled": name not in self._disabled,
            "loaded": loaded is not None,
            "has_router": loaded.router is not None if loaded else False,
            "route_prefix": f"/api/v1/{dir_name}" if loaded and loaded.router else None,
            "has_models": bool(loaded.models) if loaded else False,
            "dependency_tree": self.get_dependency_tree(name),
        }

    def get_dependency_tree(self, name: str) -> dict[str, Any]:
        """Returns which modules depend on this module (for disable warnings)."""
        if name not in self._manifests:
            raise ValueError(f"Unknown module: {name}")

        # Find all modules that list `name` in their depends
        dependents: list[str] = []
        optional_dependents: list[str] = []
        for mod_name, manifest in self._manifests.items():
            if mod_name == name:
                continue
            if name in manifest.depends:
                dependents.append(mod_name)
            if name in manifest.optional_depends:
                optional_dependents.append(mod_name)

        return {
            "module": name,
            "depends_on": self._manifests[name].depends,
            "optional_depends_on": self._manifests[name].optional_depends,
            "dependents": dependents,
            "optional_dependents": optional_dependents,
            "enabled_dependents": [d for d in dependents if d not in self._disabled],
        }


# Global singleton
module_loader = ModuleLoader()
