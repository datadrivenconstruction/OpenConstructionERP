"""Module plugin manager — download, install, update, uninstall modules.

Modules are distributed as zip archives with a standard structure:
    module-name/
    ├── manifest.py
    ├── models.py
    ├── router.py
    ├── ...
    └── locales/          # Module-specific translations
        ├── en.json
        └── de.json

Install flow:
    1. Download zip from registry URL or local file
    2. Validate manifest (deps, version compatibility)
    3. Extract to modules/ directory
    4. Run module migrations (if any)
    5. Reload module loader

Usage:
    manager = ModulePluginManager(modules_dir, registry_url)
    await manager.install("oe-rsmeans-connector", version="1.2.0")
    await manager.uninstall("oe-rsmeans-connector")
    available = await manager.list_available()
"""

import logging
import shutil
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default community module registry
DEFAULT_REGISTRY_URL = "https://registry.openestimate.io/api/v1"


@dataclass
class ModuleInfo:
    """Module metadata from registry."""

    name: str
    display_name: str
    version: str
    description: str = ""
    author: str = ""
    category: str = "community"
    depends: list[str] = field(default_factory=list)
    download_url: str = ""
    size_bytes: int = 0
    downloads: int = 0
    rating: float = 0.0
    languages: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    license: str = "MIT"
    homepage: str = ""
    min_core_version: str = "0.1.0"


class ModulePluginManager:
    """Manages module installation lifecycle."""

    def __init__(
        self,
        modules_dir: Path,
        registry_url: str = DEFAULT_REGISTRY_URL,
    ) -> None:
        self.modules_dir = modules_dir
        self.registry_url = registry_url
        self._http = httpx.AsyncClient(timeout=60.0)

    # ── Install ─────────────────────────────────────────────────────────

    async def install_from_zip(self, zip_path: Path) -> ModuleInfo:
        """Install a module from a local zip file."""
        logger.info("Installing module from %s", zip_path)

        with zipfile.ZipFile(zip_path, "r") as zf:
            return await self._install_from_zipfile(zf)

    async def install_from_url(self, url: str) -> ModuleInfo:
        """Download and install a module from URL."""
        logger.info("Downloading module from %s", url)

        resp = await self._http.get(url)
        resp.raise_for_status()

        zf = zipfile.ZipFile(BytesIO(resp.content))
        return await self._install_from_zipfile(zf)

    async def install(self, module_name: str, version: str | None = None) -> ModuleInfo:
        """Install from registry by name."""
        info = await self._fetch_module_info(module_name, version)
        if not info or not info.download_url:
            raise ValueError(f"Module not found in registry: {module_name}")

        # Check dependencies
        for dep in info.depends:
            dep_dir = self.modules_dir / dep.removeprefix("oe_")
            if not dep_dir.exists():
                logger.info("Installing dependency: %s", dep)
                await self.install(dep)

        return await self.install_from_url(info.download_url)

    async def _install_from_zipfile(self, zf: zipfile.ZipFile) -> ModuleInfo:
        """Extract and validate a module zip."""
        # Find manifest
        manifest_paths = [n for n in zf.namelist() if n.endswith("manifest.py")]
        if not manifest_paths:
            raise ValueError("No manifest.py found in module zip")

        # Determine module directory name
        top_dir = manifest_paths[0].split("/")[0]
        target = self.modules_dir / top_dir

        # Backup if already exists
        if target.exists():
            backup = target.with_suffix(".bak")
            if backup.exists():
                shutil.rmtree(backup)
            target.rename(backup)
            logger.info("Backed up existing module to %s", backup)

        # Extract
        zf.extractall(self.modules_dir)
        logger.info("Extracted module to %s", target)

        # Read manifest to return info
        # (We can't import it directly, so we read basic info)
        info = ModuleInfo(
            name=top_dir,
            display_name=top_dir.replace("_", " ").replace("-", " ").title(),
            version="unknown",
        )

        logger.info("Module installed: %s", info.name)
        return info

    # ── Uninstall ───────────────────────────────────────────────────────

    async def uninstall(self, module_name: str, keep_data: bool = True) -> None:
        """Remove a module from the modules directory."""
        dir_name = module_name.removeprefix("oe_").removeprefix("oe-")
        target = self.modules_dir / dir_name

        if not target.exists():
            raise FileNotFoundError(f"Module not found: {dir_name}")

        if keep_data:
            logger.info("Uninstalling module %s (keeping data)", module_name)
        else:
            logger.info("Uninstalling module %s (removing all data)", module_name)

        shutil.rmtree(target)
        logger.info("Module removed: %s", module_name)

    # ── Registry ────────────────────────────────────────────────────────

    async def list_available(
        self,
        category: str | None = None,
        search: str | None = None,
    ) -> list[ModuleInfo]:
        """List available modules from registry."""
        try:
            params: dict[str, Any] = {}
            if category:
                params["category"] = category
            if search:
                params["q"] = search

            resp = await self._http.get(f"{self.registry_url}/modules", params=params)
            resp.raise_for_status()
            data = resp.json()

            return [ModuleInfo(**m) for m in data.get("modules", [])]
        except Exception:
            logger.warning("Could not fetch module registry (offline mode)")
            return []

    async def list_installed(self) -> list[dict[str, Any]]:
        """List locally installed modules."""
        installed = []
        for d in sorted(self.modules_dir.iterdir()):
            if not d.is_dir() or d.name.startswith(("_", ".")):
                continue
            manifest = d / "manifest.py"
            info = {
                "name": d.name,
                "has_manifest": manifest.exists(),
                "has_locales": (d / "locales").is_dir(),
                "has_models": (d / "models.py").is_file(),
                "has_router": (d / "router.py").is_file(),
            }
            installed.append(info)
        return installed

    async def check_updates(self) -> list[dict[str, Any]]:
        """Check which installed modules have updates available."""
        # TODO: compare installed versions with registry
        return []

    async def _fetch_module_info(
        self,
        module_name: str,
        version: str | None = None,
    ) -> ModuleInfo | None:
        """Fetch module info from registry."""
        try:
            url = f"{self.registry_url}/modules/{module_name}"
            if version:
                url += f"?version={version}"
            resp = await self._http.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return ModuleInfo(**resp.json())
        except Exception:
            logger.warning("Could not fetch module info: %s", module_name)
            return None

    async def close(self) -> None:
        await self._http.aclose()
