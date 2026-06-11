"""Discover partner packs - via pip entry-points and via the repo ``packs/`` dir.

A partner pack registers via the entry-point group
``openconstructionerp.partner_packs``::

    [project.entry-points."openconstructionerp.partner_packs"]
    batimatech-ca = "openconstructionerp_batimatech_ca:MANIFEST"

The value must point at a module-level attribute that is either:
  * a ``PartnerPackManifest`` instance, OR
  * a ``dict`` the loader coerces into one.

In addition to pip-installed packs, ``discover_packs()`` also scans the
monorepo ``packs/`` directory so that source-checkout packs are listable on
the /modules page WITHOUT being pip-installed. Filesystem-discovered packs are
listable but are NEVER auto-activated - only an explicit ``OE_PARTNER_PACK``
env var activates a pack (see ``get_active_pack``).

At boot, ``discover_packs()`` enumerates every source. ``get_active_pack()``
picks one based on the precedence:

  1. env var ``OE_PARTNER_PACK`` (matches manifest.slug)
  2. None  - the platform runs in vanilla OCERP mode
"""

from __future__ import annotations

import importlib.util
import logging
import os
import zipfile
from functools import lru_cache
from importlib import resources
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from app.core.module_state import _resolve_data_dir
from app.core.partner_pack._safe_extract import (
    UnsafeArchiveError,
    resolve_single_top_level,
    safe_extract_all,
)
from app.core.partner_pack.manifest import PartnerPackManifest

logger = logging.getLogger(__name__)

# Canonical entry-point group under the Packs umbrella, plus the legacy group
# external packs already register under. Both are read (union) so packs shipped
# against either name keep loading; ``OLD`` first means a pack that for some
# reason registers under both is resolved once, with the new group winning.
ENTRY_POINT_GROUP = "openconstructionerp.packs"
ENTRY_POINT_GROUP_LEGACY = "openconstructionerp.partner_packs"
ENTRY_POINT_GROUPS = (ENTRY_POINT_GROUP_LEGACY, ENTRY_POINT_GROUP)


def _iter_entry_points() -> list[EntryPoint]:
    """Return entry-points from both the new and legacy pack groups (union).

    Reads ``openconstructionerp.partner_packs`` (legacy) and
    ``openconstructionerp.packs`` (canonical). When the same entry-point name
    appears in both groups the later group (canonical) wins, but external packs
    registered only under the legacy group still load.
    """
    by_name: dict[str, EntryPoint] = {}
    for group in ENTRY_POINT_GROUPS:
        try:
            eps = entry_points(group=group)
        except TypeError:
            # Python 3.9 fallback (the codebase requires 3.12 but be defensive).
            eps = entry_points().get(group, [])  # type: ignore[assignment]
        for ep in eps:
            by_name[ep.name] = ep
    return list(by_name.values())


# Repo root is five levels up from this file:
#   backend/app/core/partner_pack/discovery.py -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PACKS_DIR = _REPO_ROOT / "packs"

# Name of the declarative manifest a dropped (data-dir) pack must contain.
# Unlike repo/source-checkout packs (which ship a Python ``manifest.py`` that
# the core imports), data-dir packs ship a serialized ``PartnerPackManifest``
# as JSON and are NEVER executed - see ``_discover_data_dir_packs``.
DATA_DIR_MANIFEST_FILENAME = "manifest.json"

# Sub-directory of the runtime data dir scanned for dropped packs. A pack
# dropped here is a folder (or an extracted folder) whose root contains
# ``manifest.json``; a dropped ``.zip`` is safely extracted in place first.
PACKS_SUBDIR = "packs"


def _coerce_manifest(value: object) -> PartnerPackManifest:
    """Accept either a manifest instance or a dict and return a manifest."""
    if isinstance(value, PartnerPackManifest):
        return value
    if isinstance(value, dict):
        return PartnerPackManifest(**value)
    raise TypeError(f"Partner pack entry-point must point at a PartnerPackManifest or dict, got {type(value).__name__}")


def _load_one(ep: EntryPoint) -> PartnerPackManifest | None:
    """Resolve a single entry-point into a manifest, logging failures."""
    try:
        target = ep.load()
        return _coerce_manifest(target)
    except Exception as exc:  # noqa: BLE001 - boot-time best-effort
        logger.warning(
            "Partner pack '%s' failed to load: %s. Skipping.",
            ep.name,
            exc,
            exc_info=True,
        )
        return None


def _discover_entrypoint_packs() -> list[PartnerPackManifest]:
    """Return all packs registered via the pip entry-point groups (union)."""
    manifests: list[PartnerPackManifest] = []
    for ep in _iter_entry_points():
        manifest = _load_one(ep)
        if manifest:
            manifests.append(manifest)
    return manifests


def _load_manifest_from_file(manifest_path: Path) -> PartnerPackManifest | None:
    """Import a pack ``manifest.py`` by file path and read its ``MANIFEST``.

    Uses a unique synthetic module name so the import never collides with
    other packs (or a pip-installed copy of the same pack) in ``sys.modules``.
    """
    # The package dir is the parent of manifest.py, e.g.
    #   packs/<slug>/src/openconstructionerp_<pkg>/manifest.py
    pkg_dir = manifest_path.parent
    synthetic_name = f"_oe_fs_pack_{pkg_dir.name}"
    try:
        spec = importlib.util.spec_from_file_location(synthetic_name, manifest_path)
        if spec is None or spec.loader is None:
            logger.warning(
                "Could not build import spec for partner pack manifest %s. Skipping.",
                manifest_path,
            )
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest = getattr(module, "MANIFEST", None)
        if manifest is None:
            logger.warning(
                "Partner pack manifest %s has no MANIFEST attribute. Skipping.",
                manifest_path,
            )
            return None
        return _coerce_manifest(manifest)
    except Exception as exc:  # noqa: BLE001 - best-effort filesystem scan
        logger.warning(
            "Filesystem partner pack at %s failed to load: %s. Skipping.",
            manifest_path,
            exc,
            exc_info=True,
        )
        return None


def _discover_filesystem_packs() -> list[PartnerPackManifest]:
    """Scan the repo ``packs/`` dir for source-checkout packs.

    Looks for ``packs/<slug>/src/openconstructionerp_*/manifest.py``. Packs
    whose package dir contains a ``DEPRECATED.txt`` (anywhere under the pack)
    are skipped. Returns ``[]`` if the ``packs/`` dir does not exist.
    """
    if not _PACKS_DIR.is_dir():
        return []

    manifests: list[PartnerPackManifest] = []
    for pack_dir in sorted(_PACKS_DIR.iterdir()):
        if not pack_dir.is_dir():
            continue
        # Skip deprecated packs (a DEPRECATED.txt anywhere inside the pack).
        if any(pack_dir.rglob("DEPRECATED.txt")):
            continue
        src_dir = pack_dir / "src"
        if not src_dir.is_dir():
            continue
        for pkg_dir in sorted(src_dir.glob("openconstructionerp_*")):
            manifest_path = pkg_dir / "manifest.py"
            if not manifest_path.is_file():
                continue
            manifest = _load_manifest_from_file(manifest_path)
            if manifest:
                manifests.append(manifest)
    return manifests


# ── Data-dir (dropped) packs ────────────────────────────────────────────────
# Pip / VPS users have no repo checkout, so the repo ``packs/`` folder is
# unreachable and there is no place to "drop a pack". The runtime data dir
# (where the DB + partner_pack_state.json live) gets a ``packs/`` sub-folder
# that IS scanned. A dropped pack is purely declarative: a ``manifest.json``
# (a serialized PartnerPackManifest) plus its assets. We NEVER import or exec
# anything from a data-dir pack - that is the security crux of this feature.


def _data_dir_packs_dir(data_dir: Path | None = None) -> Path:
    """Return ``<data_dir>/packs`` - the scanned drop folder for dropped packs."""
    return _resolve_data_dir(data_dir) / PACKS_SUBDIR


def _load_data_dir_manifest(manifest_path: Path) -> PartnerPackManifest | None:
    """Load a declarative ``manifest.json`` into a manifest, logging failures.

    The file is parsed as JSON and validated against the Pydantic schema. It is
    NEVER imported or executed, so a dropped pack cannot run code. Returns
    ``None`` (with a logged warning) on any error so one bad pack never breaks
    discovery of the others.
    """
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        return PartnerPackManifest.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001 - best-effort filesystem scan
        logger.warning(
            "Data-dir partner pack manifest %s is invalid: %s. Skipping.",
            manifest_path,
            exc,
        )
        return None


def _manifest_dir_in(root: Path) -> Path | None:
    """Find the directory under ``root`` that holds ``manifest.json``.

    Accepts the manifest either directly under ``root`` or one level down in a
    single wrapping sub-directory (the common ``<pack>/manifest.json`` layout).
    Returns the directory containing the manifest, or ``None`` if not found.
    """
    direct = root / DATA_DIR_MANIFEST_FILENAME
    if direct.is_file():
        return root
    # Single wrapping sub-directory (e.g. an extracted ``my-pack/`` folder).
    subdirs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("__MACOSX", "."))]
    if len(subdirs) == 1 and (subdirs[0] / DATA_DIR_MANIFEST_FILENAME).is_file():
        return subdirs[0]
    return None


def _extract_dropped_zip(zip_path: Path, packs_dir: Path) -> None:
    """Safely extract a dropped ``<slug>.zip`` into ``<packs_dir>/<slug>/``.

    The extraction is staged and validated member-by-member (see
    ``_safe_extract``). A zip that is structurally broken or contains no valid
    ``manifest.json`` is left untouched and logged - never crashes discovery,
    never executes anything. If a folder of the same name already exists the
    zip is assumed already extracted and skipped (idempotent on rescan).

    The destination folder name is the zip's stem; the manifest's own ``slug``
    is authoritative for activation, so a mismatched filename is harmless.
    """
    target = packs_dir / zip_path.stem
    if target.exists():
        return  # Already extracted (or a same-named folder exists) - idempotent.

    if not zipfile.is_zipfile(zip_path):
        logger.warning("Dropped pack %s is not a valid zip archive. Ignoring.", zip_path)
        return

    import shutil
    import tempfile

    staging = Path(tempfile.mkdtemp(prefix="oe_pack_extract_"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            safe_extract_all(zf, staging)
        pack_root = resolve_single_top_level(staging)
        if not (pack_root / DATA_DIR_MANIFEST_FILENAME).is_file():
            logger.warning(
                "Dropped pack zip %s has no %s; ignoring.",
                zip_path,
                DATA_DIR_MANIFEST_FILENAME,
            )
            return
        if _load_data_dir_manifest(pack_root / DATA_DIR_MANIFEST_FILENAME) is None:
            logger.warning("Dropped pack zip %s has an invalid manifest; ignoring.", zip_path)
            return
        # Atomic move into the scanned location under the zip's stem.
        packs_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pack_root), str(target))
        logger.info("Extracted dropped partner pack %s -> %s", zip_path.name, target)
    except UnsafeArchiveError as exc:
        logger.warning("Refusing to extract unsafe dropped pack %s: %s", zip_path, exc)
    except Exception as exc:  # noqa: BLE001 - a bad drop must never crash discovery
        logger.warning("Failed to extract dropped pack %s: %s", zip_path, exc)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _discover_data_dir_packs(data_dir: Path | None = None) -> list[PartnerPackManifest]:
    """Scan ``<data_dir>/packs`` for dropped declarative packs.

    Handles three drop shapes, all declarative (no code execution):
      * a folder containing ``manifest.json`` at its root,
      * a folder wrapping a single sub-folder that holds ``manifest.json``,
      * a ``<slug>.zip`` which is safely extracted in place, then loaded.

    Returns ``[]`` when the drop folder does not exist. A pack that fails to
    load is skipped with a logged warning.
    """
    packs_dir = _data_dir_packs_dir(data_dir)
    if not packs_dir.is_dir():
        return []

    # 1) Extract any dropped .zip files first so the folder scan below sees them.
    for entry in sorted(packs_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() == ".zip":
            _extract_dropped_zip(entry, packs_dir)

    # 2) Scan extracted/dropped folders for a declarative manifest.json.
    manifests: list[PartnerPackManifest] = []
    for entry in sorted(packs_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("__MACOSX", ".")):
            continue
        manifest_dir = _manifest_dir_in(entry)
        if manifest_dir is None:
            continue
        manifest = _load_data_dir_manifest(manifest_dir / DATA_DIR_MANIFEST_FILENAME)
        if manifest:
            manifests.append(manifest)
    return manifests


class PackInstallError(Exception):
    """Raised when an uploaded pack archive cannot be installed.

    Carries a user-safe ``reason`` (no filesystem internals) suitable for a
    400 response body.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def install_dropped_zip(zip_bytes: bytes, data_dir: Path | None = None) -> PartnerPackManifest:
    """Validate and install a pack ``.zip`` upload into ``<data_dir>/packs/``.

    Used by the ``POST /api/v1/partner-pack/install`` endpoint. Unlike the
    passive discovery scan (``_extract_dropped_zip``), this RAISES on any
    problem so the caller can return a clear 400. The flow is:

      1. structural zip check + member-by-member safety validation (staged
         temp extraction - nothing lands in a scanned path until validated),
      2. locate the declarative ``manifest.json`` (root or single sub-folder),
      3. validate it against :class:`PartnerPackManifest` (NEVER executed),
      4. atomically move the validated tree into ``<data_dir>/packs/<slug>/``,
         keyed on the manifest's own ``slug``.

    Args:
        zip_bytes: The raw uploaded archive bytes.
        data_dir: Override the runtime data dir (tests). Defaults to the
            resolved data dir (beside the database).

    Returns:
        The validated :class:`PartnerPackManifest` of the installed pack.

    Raises:
        PackInstallError: If the upload is not a valid zip, contains an unsafe
            member, has no loadable ``manifest.json``, or a different pack with
            the same slug is already installed.
    """
    import io
    import shutil
    import tempfile

    bio = io.BytesIO(zip_bytes)
    if not zipfile.is_zipfile(bio):
        raise PackInstallError("uploaded file is not a valid zip archive")
    bio.seek(0)

    packs_dir = _data_dir_packs_dir(data_dir)
    staging = Path(tempfile.mkdtemp(prefix="oe_pack_install_"))
    try:
        with zipfile.ZipFile(bio) as zf:
            try:
                safe_extract_all(zf, staging)
            except UnsafeArchiveError as exc:
                raise PackInstallError(f"refusing to install unsafe archive: {exc}") from exc

        pack_root = resolve_single_top_level(staging)
        manifest_file = pack_root / DATA_DIR_MANIFEST_FILENAME
        if not manifest_file.is_file():
            raise PackInstallError(
                f"archive does not contain a {DATA_DIR_MANIFEST_FILENAME} (a serialized partner-pack manifest)"
            )
        try:
            manifest = PartnerPackManifest.model_validate_json(manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - surface the validation reason
            raise PackInstallError(f"{DATA_DIR_MANIFEST_FILENAME} is not a valid partner-pack manifest: {exc}") from exc

        target = packs_dir / manifest.slug
        if target.exists():
            # Don't clobber an existing same-slug pack - make the conflict explicit.
            raise PackInstallError(
                f"a pack with slug '{manifest.slug}' is already installed; remove it first or rename this one"
            )

        packs_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pack_root), str(target))
        logger.info("Installed uploaded partner pack '%s' -> %s", manifest.slug, target)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@lru_cache(maxsize=1)
def discover_packs() -> list[PartnerPackManifest]:
    """Return all discoverable packs (entry-points + repo + data-dir drops).

    Sources, lowest to highest precedence on slug collision:
      1. data-dir dropped packs (``<data_dir>/packs/``, declarative JSON)
      2. repo source-checkout packs (``packs/<slug>/src/...``, Python manifest)
      3. pip entry-point packs

    Results are deduped by slug and sorted alphabetically. Cached for the
    lifetime of the process; call ``discover_packs.cache_clear()`` (or
    ``reset_cache()``) in tests that install or remove a pack at runtime.
    Dropped packs are listable but, like repo packs, are NEVER auto-activated.
    """
    by_slug: dict[str, PartnerPackManifest] = {}

    # Data-dir drops first (lowest precedence), then filesystem, then
    # entry-points - so a pip-installed pack always wins on a slug collision.
    for manifest in _discover_data_dir_packs():
        by_slug[manifest.slug] = manifest
    for manifest in _discover_filesystem_packs():
        by_slug[manifest.slug] = manifest
    for manifest in _discover_entrypoint_packs():
        by_slug[manifest.slug] = manifest

    manifests = sorted(by_slug.values(), key=lambda m: m.slug)
    if manifests:
        logger.info(
            "Discovered %d partner pack(s): %s",
            len(manifests),
            ", ".join(m.slug for m in manifests),
        )
    return manifests


def get_pack_by_slug(slug: str) -> PartnerPackManifest | None:
    """Return the discovered pack whose slug matches, or None."""
    for m in discover_packs():
        if m.slug == slug:
            return m
    return None


def get_active_pack() -> PartnerPackManifest | None:
    """Pick the active pack.

    A pack becomes active either by being *applied* in-app (persisted via the
    /modules Partner Packs tab) or by the ``OE_PARTNER_PACK`` env var. Merely
    discovering packs (including the source-checkout packs under ``packs/``)
    never co-brands the app.

    Precedence:
      1. in-app applied pack (``partner_pack_state.json`` in the ACTIVE
         data dir - see ``state._resolve_state_dir``)
      2. env ``OE_PARTNER_PACK=<slug>``
      3. None

    Cached per resolved state dir, so two instances resolving different data
    dirs never share an answer; ``reset_cache()`` is called by the apply
    service after an apply / un-apply so the change takes effect immediately.
    """
    # Resolve the state dir HERE (live, uncached) and key the cache on it.
    # Imported lazily to avoid any import-order issues.
    try:
        from app.core.partner_pack.state import _resolve_state_dir

        state_dir = str(_resolve_state_dir())
    except Exception:  # noqa: BLE001 - state resolution is best-effort
        state_dir = ""
    return _get_active_pack_cached(state_dir)


@lru_cache(maxsize=8)
def _get_active_pack_cached(state_dir: str) -> PartnerPackManifest | None:
    """Resolve the active pack for one specific state dir (cached per path)."""
    # 1. In-app applied pack, read from the keyed state dir only.
    applied = None
    if state_dir:
        try:
            from app.core.partner_pack.state import get_applied_slug

            applied = get_applied_slug(Path(state_dir))
        except Exception:  # noqa: BLE001 - state file is best-effort
            applied = None
    if applied:
        m = get_pack_by_slug(applied)
        if m:
            logger.info("Active partner pack (in-app applied): %s", m.slug)
            return m
        logger.warning(
            "Applied partner pack '%s' is no longer installed; falling back.",
            applied,
        )

    # 2. env var. OE_PACK is the canonical name under the Packs umbrella;
    #    OE_PARTNER_PACK is kept as a backward-compatible alias. OE_PACK wins
    #    if both are set so existing installs keep working unchanged.
    requested = os.environ.get("OE_PACK", "").strip() or os.environ.get("OE_PARTNER_PACK", "").strip()
    if requested:
        m = get_pack_by_slug(requested)
        if m:
            logger.info("Active pack (env-selected): %s", m.slug)
            return m
        logger.warning(
            "OE_PACK/OE_PARTNER_PACK=%s requested but no such pack is installed.",
            requested,
        )
    return None


def get_active_pack_module_name() -> str | None:
    """Return the Python module name of the active pack, for resource loading.

    Resolves to e.g. ``openconstructionerp_batimatech_ca``. Used by
    ``router.py`` to stream the partner logo and onboarding script out of
    the installed pack package via ``importlib.resources``.

    Only pip-installed (entry-point) packs expose an importable module name;
    filesystem-only packs return ``None`` here (their resources are not on the
    import path). Since activation is env-driven and partners ship pip-installed
    packs in production, this matches the resource-streaming contract.
    """
    active = get_active_pack()
    if not active:
        return None
    for ep in _iter_entry_points():
        if ep.name == active.slug:
            # ep.value is "module:attr" - return the module part
            return ep.value.split(":", 1)[0]
    return None


def _entrypoint_module_for_slug(slug: str) -> str | None:
    """Return the Python module name for a pip-installed pack by slug, or None."""
    for ep in _iter_entry_points():
        if ep.name == slug:
            return ep.value.split(":", 1)[0]
    return None


def _fs_package_dir_for_slug(slug: str) -> Path | None:
    """Locate the on-disk package dir for a source-checkout pack by slug."""
    if not _PACKS_DIR.is_dir():
        return None

    def _pkg_dirs(pack_dir: Path) -> list[Path]:
        src_dir = pack_dir / "src"
        if not src_dir.is_dir():
            return []
        return [
            d for d in sorted(src_dir.glob("openconstructionerp_*")) if d.is_dir() and not d.name.endswith(".egg-info")
        ]

    # Fast path: the pack directory name matches the slug (repo convention).
    direct = _PACKS_DIR / slug
    for pkg_dir in _pkg_dirs(direct):
        if (pkg_dir / "manifest.py").is_file():
            return pkg_dir

    # Fallback: scan every pack and match the loaded manifest slug.
    for pack_dir in sorted(_PACKS_DIR.iterdir()):
        if not pack_dir.is_dir() or pack_dir == direct:
            continue
        for pkg_dir in _pkg_dirs(pack_dir):
            manifest_path = pkg_dir / "manifest.py"
            if not manifest_path.is_file():
                continue
            m = _load_manifest_from_file(manifest_path)
            if m and m.slug == slug:
                return pkg_dir
    return None


def _data_dir_package_dir_for_slug(slug: str, data_dir: Path | None = None) -> Path | None:
    """Locate the on-disk directory of a dropped (data-dir) pack by slug.

    Matches on the manifest's ``slug`` (authoritative), not on the folder name,
    so a pack dropped under any folder/zip name still resolves. Returns the
    directory that contains ``manifest.json`` (and the pack's assets), or
    ``None`` if no dropped pack declares that slug.
    """
    packs_dir = _data_dir_packs_dir(data_dir)
    if not packs_dir.is_dir():
        return None
    for entry in sorted(packs_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("__MACOSX", ".")):
            continue
        manifest_dir = _manifest_dir_in(entry)
        if manifest_dir is None:
            continue
        m = _load_data_dir_manifest(manifest_dir / DATA_DIR_MANIFEST_FILENAME)
        if m and m.slug == slug:
            return manifest_dir
    return None


def _read_sandboxed(base: Path, rel: str) -> bytes | None:
    """Read ``base/rel`` only if it resolves to a file inside ``base``."""
    base = base.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    if target.is_file():
        return target.read_bytes()
    return None


def read_pack_file(slug: str, relpath: str) -> bytes | None:
    """Read a file shipped inside a pack package, addressed by slug.

    Resolves, in order:
      1. pip-installed (entry-point) packs via ``importlib.resources``,
      2. source-checkout packs under ``packs/<slug>/src/``,
      3. dropped packs under ``<data_dir>/packs/`` (assets beside manifest.json).

    Path-traversal safe in every branch. Returns ``None`` when the pack or the
    file cannot be found. This is the by-slug counterpart to
    ``router._read_pack_resource`` (which only reads the active pack); the
    /modules grid uses it to show each pack's own logo.
    """
    rel = relpath.lstrip("/\\")
    if not rel or ".." in Path(rel.replace("\\", "/")).parts:
        return None

    # 1) pip-installed pack - read via importlib.resources.
    mod_name = _entrypoint_module_for_slug(slug)
    if mod_name:
        try:
            target = resources.files(mod_name).joinpath(rel)
            if target.is_file():
                return target.read_bytes()
        except (
            ModuleNotFoundError,
            FileNotFoundError,
            AttributeError,
            NotADirectoryError,
        ):
            pass

    # 2) source-checkout pack - read from the packs/ directory, sandboxed.
    pkg_dir = _fs_package_dir_for_slug(slug)
    if pkg_dir:
        data = _read_sandboxed(pkg_dir, rel)
        if data is not None:
            return data

    # 3) dropped (data-dir) pack - assets sit beside manifest.json, sandboxed.
    dropped_dir = _data_dir_package_dir_for_slug(slug)
    if dropped_dir:
        return _read_sandboxed(dropped_dir, rel)

    return None


def reset_cache() -> None:
    """Reset the discovery caches. Used by tests and the apply service."""
    discover_packs.cache_clear()
    _get_active_pack_cached.cache_clear()
