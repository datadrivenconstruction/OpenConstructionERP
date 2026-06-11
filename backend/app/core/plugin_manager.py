"""‌⁠‍Module plugin manager - download, install, update, uninstall modules.

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

import importlib.util
import logging
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Leading numeric "release" segment of a version, e.g. "1.2.0" from "1.2.0-rc1".
_VERSION_RELEASE_RE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


def _version_key(version: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple of release integers.

    Tolerates a leading ``v``, pre-release/build suffixes (``1.2.0-rc1``), and
    non-numeric junk by extracting only the leading dotted-integer release
    segment. An unparseable string yields an empty tuple, which sorts lowest.
    """
    match = _VERSION_RELEASE_RE.match(version or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


# Default community module registry.
#
# There is no public module registry service today (the old
# registry.openestimate.io host is gone), so the default is empty and every
# registry-backed operation is an explicit no-op with a clear message instead
# of a network call that silently fails. Local zip installs are unaffected.
# Operators running a self-hosted registry pass its URL to the constructor.
DEFAULT_REGISTRY_URL = ""


@dataclass
class ModuleInfo:
    """‌⁠‍Module metadata from registry."""

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
    """‌⁠‍Manages module installation lifecycle."""

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
        if not self.registry_url:
            raise ValueError(
                "No module registry is configured. Install from a local zip with "
                "install_from_zip(), or pass a registry_url to ModulePluginManager."
            )
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

        # Read the extracted manifest to return real metadata. The manifest
        # defines a ``manifest = ModuleManifest(...)`` module-level variable
        # (same contract as ModuleLoader.discover). Load it from the extracted
        # file rather than guessing, so the returned ModuleInfo carries the
        # real version / display_name / dependencies.
        manifest_file = target / "manifest.py"
        try:
            manifest = self._load_manifest(manifest_file)
        except Exception as exc:
            # Roll back the extraction so a broken zip never leaves a partially
            # installed module behind, then restore the backup if there was one.
            shutil.rmtree(target, ignore_errors=True)
            backup = target.with_suffix(".bak")
            if backup.exists():
                backup.rename(target)
                logger.info("Restored backup after failed install: %s", target)
            raise ValueError(f"Invalid module manifest in {top_dir}: {exc}") from exc

        info = ModuleInfo(
            name=manifest.name,
            display_name=manifest.display_name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            category=manifest.category,
            depends=list(manifest.depends),
        )

        logger.info("Module installed: %s v%s", info.name, info.version)
        return info

    @staticmethod
    def _load_manifest(manifest_file: Path) -> Any:
        """Safely load the ``manifest`` object from an extracted manifest.py.

        Args:
            manifest_file: Path to the module's extracted ``manifest.py``.

        Returns:
            The ``ModuleManifest`` instance defined in the file.

        Raises:
            ValueError: If the file is missing or defines no valid manifest.
        """
        from app.core.module_loader import ModuleManifest

        if not manifest_file.is_file():
            raise ValueError("manifest.py not found")

        spec = importlib.util.spec_from_file_location(
            f"_oe_plugin_manifest_{manifest_file.parent.name}",
            manifest_file,
        )
        if spec is None or spec.loader is None:
            raise ValueError("could not load manifest.py")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        manifest = getattr(module, "manifest", None)
        if not isinstance(manifest, ModuleManifest):
            raise ValueError("manifest.py does not define a ModuleManifest named 'manifest'")
        return manifest

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
        """List available modules from registry.

        Returns an empty list (an explicit empty state, no network call) when
        no registry is configured.
        """
        if not self.registry_url:
            logger.info("No module registry configured; returning empty catalog")
            return []
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
            manifest_file = d / "manifest.py"
            manifest = self._read_installed_manifest(manifest_file)
            info = {
                "name": manifest.name if manifest else d.name,
                "version": manifest.version if manifest else None,
                "has_manifest": manifest_file.exists(),
                "has_locales": (d / "locales").is_dir(),
                "has_models": (d / "models.py").is_file(),
                "has_router": (d / "router.py").is_file(),
            }
            installed.append(info)
        return installed

    def _read_installed_manifest(self, manifest_file: Path) -> Any | None:
        """Load an installed manifest, swallowing errors (best-effort metadata).

        Returns:
            The ``ModuleManifest`` instance, or ``None`` if it could not be read.
        """
        if not manifest_file.is_file():
            return None
        try:
            return self._load_manifest(manifest_file)
        except Exception:
            logger.debug("Could not read manifest at %s", manifest_file)
            return None

    @staticmethod
    def _is_newer(available: str, installed: str) -> bool:
        """Return True if ``available`` is a newer version than ``installed``.

        Compares the leading numeric release segments (semver-style). When both
        sides are unparseable (no numeric release), falls back to a
        case-insensitive string inequality so a differing tag still flags an
        update rather than silently hiding it.
        """
        avail_key = _version_key(available)
        inst_key = _version_key(installed)
        if avail_key and inst_key:
            return avail_key > inst_key
        if avail_key and not inst_key:
            # Installed version is junk but a clean release is offered → upgrade.
            return True
        return available.strip().lower() != installed.strip().lower()

    async def check_updates(self) -> list[dict[str, Any]]:
        """Check which installed modules have a newer version in the registry.

        Compares each locally installed module's manifest version against the
        version advertised by the registry (via :meth:`list_available`). Modules
        with no manifest version, no registry entry, or an up-to-date version are
        skipped. Returns one entry per upgradable module.

        Returns:
            A list of ``{name, installed_version, available_version}`` dicts for
            modules where the registry offers a newer version. Empty when offline
            or when everything is current.
        """
        available = await self.list_available()
        if not available:
            return []

        latest: dict[str, ModuleInfo] = {}
        for remote in available:
            existing = latest.get(remote.name)
            if existing is None or self._is_newer(remote.version, existing.version):
                latest[remote.name] = remote

        updates: list[dict[str, Any]] = []
        for local in await self.list_installed():
            installed_version = local.get("version")
            if not installed_version:
                continue
            remote = latest.get(local["name"])
            if remote and remote.version and self._is_newer(remote.version, installed_version):
                updates.append(
                    {
                        "name": local["name"],
                        "installed_version": installed_version,
                        "available_version": remote.version,
                    }
                )
        return updates

    async def _fetch_module_info(
        self,
        module_name: str,
        version: str | None = None,
    ) -> ModuleInfo | None:
        """Fetch module info from registry. ``None`` when no registry is configured."""
        if not self.registry_url:
            return None
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
