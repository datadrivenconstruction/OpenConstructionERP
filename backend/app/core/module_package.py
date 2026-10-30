# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Install third-party module ZIPs from the admin UI.

Trust model, stated plainly: a module package is Python that runs inside the
server with the same rights as the platform. Python cannot be sandboxed, so
nothing here makes untrusted code safe. What this does guarantee is that the
archive is never imported or executed before an administrator has seen every
file and confirmed the install, that it can only write into the runtime module
directory, and that a failed install leaves the existing modules untouched.

The archive format is the CLI's (``openconstructionerp module install``): one
top-level package directory with a ``manifest.py``. An optional data-only
``module.json`` next to it declares platform compatibility and one hosted UI
page for the sidebar.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib
import io
import json
import logging
import re
import shutil
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.module_runtime_root import attach_runtime_root, runtime_modules_dir
from app.core.partner_pack._safe_extract import UnsafeArchiveError, is_unsafe_zip_member, stage_and_extract

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_COMPRESSION_RATIO = 200
STAGING_TTL_SECONDS = 3600
MARKER_FILE = ".oe_package.json"
DESCRIPTOR_FILE = "module.json"

ALLOWED_SUFFIXES = frozenset(
    {
        ".py", ".json", ".md", ".txt", ".html", ".htm", ".js", ".mjs", ".css", ".svg", ".png", ".jpg",
        ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".csv", ".yaml", ".yml", ".toml", ".ini",
        ".sql", ".map",
    }
)  # fmt: skip
ALLOWED_BARE_NAMES = frozenset({"LICENSE", "README", "NOTICE", "py.typed"})

# Sidebar groups a module may place its page in. Kept equal to the ``grp_*``
# ids of frontend/src/app/layout/navCatalog.ts by a test.
KNOWN_NAV_GROUPS = frozenset(
    {
        "grp_overview", "grp_takeoff", "grp_cost_data", "grp_estimating", "grp_drawings", "grp_reality",
        "grp_coordination", "grp_scheduling", "grp_cost_control", "grp_commercial", "grp_procurement",
        "grp_estimate_detail", "grp_change", "grp_records", "grp_field", "grp_site", "grp_resources",
        "grp_quality", "grp_handover", "grp_safety", "grp_esg", "grp_communication", "grp_documents",
        "grp_real_estate", "grp_finance", "grp_controls_bi", "grp_estimating_ai", "grp_automation_ai", "grp_rate_buildup",
    }
)  # fmt: skip
# Mirrored by RUNTIME_MODULE_ICONS in the frontend sidebar.
ALLOWED_ICONS = frozenset(
    {"package", "puzzle", "box", "layers", "table", "chart", "calculator", "file", "clipboard", "wrench", "map"}
)
UI_MODES = frozenset({"hosted"})

_NAME_RE = re.compile(r"^oe_[a-z][a-z0-9_]{1,48}$")
_VERSION_RE = re.compile(r"^\d+(\.\d+){0,2}$")
_PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_SPEC_RE = re.compile(r"^(>=|<=|==|>|<)\s*(\d+(?:\.\d+){0,2})$")


class PackageRefused(Exception):
    """The package cannot be staged or installed; ``message`` is shown to the admin."""

    def __init__(self, message: str, code: str = "refused") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Check:
    """One validation rule applied to a package, as shown on the review screen."""

    rule_id: str
    severity: str  # "error" | "warning" | "info"
    message: str


@dataclass
class PackageFile:
    path: str
    size: int
    sha256: str


@dataclass
class Preview:
    token: str
    archive_sha256: str
    archive_size: int
    module_name: str | None
    version: str | None
    display_name: str | None
    author: str | None
    category: str | None
    depends: list[str]
    requires_platform: str | None
    ui: dict[str, Any] | None
    files: list[PackageFile]
    checks: list[Check] = field(default_factory=list)

    @property
    def installable(self) -> bool:
        return not any(c.severity == "error" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["installable"] = self.installable
        return data


# ── Small pure helpers ────────────────────────────────────────────────────


def _parse_version(text: str) -> tuple[int, int, int]:
    nums = [int(p) for p in re.findall(r"\d+", text)[:3]]
    return tuple((nums + [0, 0, 0])[:3])  # type: ignore[return-value]


def platform_version() -> str:
    from app.config import get_settings

    return get_settings().app_version


def version_satisfies(version: str, spec: str) -> bool:
    """Whether ``version`` meets a comma-separated range like ``>=18.9,<20``.

    Raises:
        ValueError: The range is not in that form.
    """
    current = _parse_version(version)
    clauses = [c.strip() for c in spec.split(",") if c.strip()]
    if not clauses:
        raise ValueError("empty range")
    for clause in clauses:
        match = _SPEC_RE.match(clause)
        if not match:
            raise ValueError(f"unsupported clause {clause!r}")
        op, bound_text = match.groups()
        bound = _parse_version(bound_text)
        ok = {
            ">=": current >= bound,
            "<=": current <= bound,
            "==": current == bound,
            ">": current > bound,
            "<": current < bound,
        }[op]
        if not ok:
            return False
    return True


def read_manifest_fields(source: str) -> dict[str, Any]:
    """Literal keyword arguments of the ``ModuleManifest(...)`` call, by ``ast`` (never executed)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if callee != "ModuleManifest":
            continue
        fields: dict[str, Any] = {}
        for kw in node.keywords:
            if kw.arg is None:
                continue
            with contextlib.suppress(ValueError):
                fields[kw.arg] = ast.literal_eval(kw.value)
        return fields
    return {}


def module_api_prefixes(module_name: str) -> tuple[str, str]:
    """The two prefixes the loader mounts a module router at (kebab and legacy)."""
    dir_name = module_name.removeprefix("oe_")
    return f"/api/v1/{dir_name.replace('_', '-')}", f"/api/v1/{dir_name}"


def validate_ui(module_name: str, ui: Any, checks: list[Check]) -> dict[str, Any] | None:
    """Validate the ``ui`` block of ``module.json``; return the normalised entry or ``None``."""
    if ui is None:
        return None
    if not isinstance(ui, dict):
        checks.append(Check("ui.shape", "error", "module.json 'ui' must be an object."))
        return None
    errors_before = len(checks)
    label = ui.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > 60:
        checks.append(Check("ui.label", "error", "ui.label must be a non-empty text of at most 60 characters."))
    group = ui.get("group")
    if group not in KNOWN_NAV_GROUPS:
        checks.append(Check("ui.group", "error", f"ui.group {group!r} is not a sidebar group of this platform."))
    icon = ui.get("icon", "package")
    if icon not in ALLOWED_ICONS:
        checks.append(Check("ui.icon", "error", f"ui.icon {icon!r} is not one of {', '.join(sorted(ALLOWED_ICONS))}."))
    mode = ui.get("mode", "hosted")
    if mode not in UI_MODES:
        checks.append(
            Check("ui.mode", "error", f"ui.mode {mode!r} is not supported yet; this version supports 'hosted'.")
        )
    param = ui.get("project_param")
    if param is not None and (not isinstance(param, str) or not _PARAM_RE.match(param)):
        checks.append(Check("ui.project_param", "error", "ui.project_param must be a lower-case identifier."))
    path = ui.get("path")
    prefixes = module_api_prefixes(module_name)
    normalised = None
    if not isinstance(path, str) or any(ch in path for ch in "\\?#%\n\r\t ") or "//" in path:
        checks.append(Check("ui.path", "error", "ui.path must be a plain same-origin path."))
    else:
        parts = PurePosixPath(path).parts
        if ".." in parts or "." in parts or not path.startswith("/"):
            checks.append(Check("ui.path", "error", "ui.path must be absolute and must not contain '.' or '..'."))
        elif not any(path == p or path.startswith(p + "/") for p in prefixes):
            checks.append(Check("ui.path", "error", f"ui.path must live under the module's own API {prefixes[0]}/."))
        else:
            normalised = path
    if len(checks) > errors_before:
        return None
    return {
        "label": label.strip(),
        "group": group,
        "icon": icon,
        "mode": mode,
        "path": normalised,
        "project_param": param,
    }


# ── Staging ───────────────────────────────────────────────────────────────


def staging_root() -> Path:
    """Where uploaded archives wait for review: beside, never inside, the module root."""
    return runtime_modules_dir().expanduser().parent / "module_staging"


def _staged_dir(token: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise PackageRefused("Unknown upload. Upload the archive again.", code="not_found")
    return staging_root() / token


def purge_expired_staging(now: float | None = None) -> None:
    root = staging_root()
    if not root.is_dir():
        return
    limit = (now or time.time()) - STAGING_TTL_SECONDS
    for entry in root.iterdir():
        with contextlib.suppress(OSError):
            if entry.is_dir() and entry.stat().st_mtime < limit:
                shutil.rmtree(entry, ignore_errors=True)


def discard(token: str) -> None:
    shutil.rmtree(_staged_dir(token), ignore_errors=True)


def inspect_archive(data: bytes, *, known_modules: dict[str, str] | None = None) -> Preview:
    """Validate an archive without extracting or executing it.

    Args:
        data: The uploaded bytes.
        known_modules: ``{manifest name: category}`` of every discovered module,
            for collision checks. Defaults to the live loader's registry.

    Raises:
        PackageRefused: The bytes are not a readable ZIP at all.
    """
    if known_modules is None:
        from app.core.module_loader import module_loader

        known_modules = {n: m.category for n, m in module_loader._manifests.items()}

    if len(data) > MAX_UPLOAD_BYTES:
        raise PackageRefused(f"The archive is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", code="too_large")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise PackageRefused("The file is not a ZIP archive.", code="not_zip")

    checks: list[Check] = []
    files: list[PackageFile] = []
    fields: dict[str, Any] = {}
    descriptor: dict[str, Any] = {}
    top = None
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PackageRefused("The ZIP archive is damaged.", code="not_zip") from exc

    with zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        if not infos:
            checks.append(Check("archive.empty", "error", "The archive is empty."))
        if len(infos) > MAX_MEMBERS:
            checks.append(Check("archive.members", "error", f"The archive has more than {MAX_MEMBERS} entries."))
        if len(set(names)) != len(names):
            checks.append(Check("archive.duplicates", "error", "The archive lists the same path twice."))
        total = sum(i.file_size for i in infos)
        if total > MAX_UNCOMPRESSED_BYTES:
            checks.append(Check("archive.size", "error", "The archive unpacks to more than 100 MB."))
        for info in infos:
            reason = is_unsafe_zip_member(info)
            if reason is not None:
                checks.append(Check("archive.unsafe_member", "error", f"Unsafe entry: {reason}."))
                continue
            if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
                checks.append(Check("archive.ratio", "error", f"{info.filename} is compressed suspiciously well."))
            if info.filename.endswith("/"):
                continue
            leaf = PurePosixPath(info.filename).name
            suffix = PurePosixPath(leaf).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES and leaf not in ALLOWED_BARE_NAMES:
                checks.append(Check("archive.file_type", "error", f"{info.filename}: this file type is not allowed."))
            if any(part.startswith(".") for part in PurePosixPath(info.filename).parts):
                checks.append(Check("archive.hidden", "error", f"{info.filename}: hidden files are not allowed."))
        if any(c.severity == "error" for c in checks):
            return _preview(data, None, fields, descriptor, files, checks)

        tops = {n.split("/", 1)[0] for n in names if n}
        if len(tops) != 1 or not any("/" in n for n in names):
            checks.append(Check("layout.single_top", "error", "The archive must hold exactly one package directory."))
            return _preview(data, None, fields, descriptor, files, checks)
        top = next(iter(tops))
        for info in infos:
            if not info.filename.endswith("/"):
                files.append(
                    PackageFile(info.filename, info.file_size, hashlib.sha256(zf.read(info)).hexdigest()),
                )
        manifest_name = f"{top}/manifest.py"
        if manifest_name not in names:
            checks.append(Check("manifest.missing", "error", f"{manifest_name} is missing."))
            return _preview(data, top, fields, descriptor, files, checks)
        try:
            fields = read_manifest_fields(zf.read(manifest_name).decode("utf-8"))
        except UnicodeDecodeError:
            fields = {}
        if f"{top}/__init__.py" not in names:
            checks.append(Check("manifest.package", "error", f"{top}/__init__.py is missing."))
        descriptor_name = f"{top}/{DESCRIPTOR_FILE}"
        if descriptor_name in names:
            try:
                descriptor = json.loads(zf.read(descriptor_name).decode("utf-8"))
                if not isinstance(descriptor, dict):
                    raise ValueError("not an object")
            except (ValueError, UnicodeDecodeError):
                descriptor = {}
                checks.append(Check("descriptor.json", "error", f"{DESCRIPTOR_FILE} is not a valid JSON object."))

    _check_manifest(top, fields, known_modules, checks)
    _check_compatibility(fields, descriptor, known_modules, checks)
    return _preview(data, top, fields, descriptor, files, checks)


def _check_manifest(top: str, fields: dict[str, Any], known: dict[str, str], checks: list[Check]) -> None:
    name = fields.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        checks.append(
            Check("manifest.name", "error", "manifest.py must declare name='oe_<lower_case_name>' as a literal.")
        )
        return
    if name.removeprefix("oe_") != top:
        checks.append(Check("manifest.dir", "error", f"The package directory must be named {name[3:]!r}."))
    if not isinstance(fields.get("version"), str) or not _VERSION_RE.match(fields["version"]):
        checks.append(Check("manifest.version", "error", "manifest.py must declare a version like '1.0.0'."))
    if not isinstance(fields.get("display_name"), str):
        checks.append(Check("manifest.display_name", "error", "manifest.py must declare display_name."))
    if fields.get("category", "core") == "core":
        checks.append(
            Check("manifest.category", "error", "A third-party module cannot be 'core'. Set category='community'.")
        )
    if name in known:
        checks.append(
            Check("manifest.collision", "error", f"A module named {name} is already installed. Uninstall it first.")
        )
    if (runtime_modules_dir().expanduser() / top).exists() and name not in known:
        checks.append(Check("manifest.collision", "error", f"The folder {top!r} already exists in the module root."))


def _check_compatibility(
    fields: dict[str, Any], descriptor: dict[str, Any], known: dict[str, str], checks: list[Check]
) -> None:
    depends = fields.get("depends") or []
    if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
        checks.append(Check("compat.depends", "error", "manifest depends must be a list of module names."))
    else:
        missing = [d for d in depends if d not in known]
        if missing:
            checks.append(Check("compat.depends", "error", f"Required modules are missing: {', '.join(missing)}."))
    spec = descriptor.get("requires_platform")
    if spec is None:
        checks.append(Check("compat.platform", "warning", "The module does not say which platform versions it fits."))
    else:
        current = platform_version()
        try:
            ok = isinstance(spec, str) and version_satisfies(current, spec)
        except ValueError:
            checks.append(Check("compat.platform", "error", f"requires_platform {spec!r} is not a version range."))
        else:
            if not ok:
                checks.append(
                    Check("compat.platform", "error", f"The module needs platform {spec}; this server runs {current}.")
                )
    checks.append(
        Check(
            "trust.python",
            "warning",
            "This package contains Python that will run on the server with full access. Install only code you trust.",
        )
    )


def _preview(
    data: bytes,
    top: str | None,
    fields: dict[str, Any],
    descriptor: dict[str, Any],
    files: list[PackageFile],
    checks: list[Check],
) -> Preview:
    name = fields.get("name") if isinstance(fields.get("name"), str) else None
    ui = validate_ui(name, descriptor.get("ui"), checks) if name and descriptor else None
    depends = fields.get("depends") if isinstance(fields.get("depends"), list) else []
    return Preview(
        token=uuid.uuid4().hex,
        archive_sha256=hashlib.sha256(data).hexdigest(),
        archive_size=len(data),
        module_name=name,
        version=fields.get("version") if isinstance(fields.get("version"), str) else None,
        display_name=fields.get("display_name") if isinstance(fields.get("display_name"), str) else None,
        author=fields.get("author") if isinstance(fields.get("author"), str) else None,
        category=fields.get("category") if isinstance(fields.get("category"), str) else None,
        depends=[d for d in depends if isinstance(d, str)],
        requires_platform=descriptor.get("requires_platform") if isinstance(descriptor, dict) else None,
        ui=ui,
        files=files,
        checks=checks,
    )


def stage(data: bytes) -> Preview:
    """Inspect an upload and keep it for the install step, whatever the verdict."""
    purge_expired_staging()
    preview = inspect_archive(data)
    target = staging_root() / preview.token
    target.mkdir(parents=True, exist_ok=True)
    (target / "archive.zip").write_bytes(data)
    (target / "preview.json").write_text(json.dumps(preview.to_dict()), encoding="utf-8")
    return preview


# ── Install / uninstall ───────────────────────────────────────────────────


def read_marker(package_dir: Path) -> dict[str, Any] | None:
    marker = package_dir / MARKER_FILE
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def installed_packages() -> list[dict[str, Any]]:
    """Every module that was installed from a ZIP, with its marker."""
    root = runtime_modules_dir().expanduser()
    if not root.is_dir():
        return []
    out = []
    for entry in sorted(root.iterdir()):
        marker = read_marker(entry) if entry.is_dir() else None
        if marker:
            out.append(marker)
    return out


def _module_tables(module_name: str) -> list[Any]:
    dir_name = module_name.removeprefix("oe_")
    try:
        models = importlib.import_module(f"app.modules.{dir_name}.models")
    except ModuleNotFoundError:
        return []
    return [
        obj.__table__
        for obj in vars(models).values()
        if isinstance(obj, type) and getattr(obj, "__module__", None) == models.__name__ and hasattr(obj, "__table__")
    ]


async def create_missing_tables(module_name: str) -> list[str]:
    """Create this module's tables that do not exist yet. Additive only: nothing is altered or dropped."""
    tables = _module_tables(module_name)
    if not tables:
        return []
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables, checkfirst=True))
    return [t.name for t in tables]


async def install(token: str, app: Any, *, enable: bool, actor: str | None) -> dict[str, Any]:
    """Install a staged archive into the runtime module root and optionally mount it.

    Raises:
        PackageRefused: The upload is gone, changed, or no longer passes the checks,
            or the module failed to load (its files are then removed again).
    """
    from app.core.module_loader import module_loader

    staged = _staged_dir(token)
    archive = staged / "archive.zip"
    if not archive.is_file():
        raise PackageRefused("Unknown upload. Upload the archive again.", code="not_found")
    data = archive.read_bytes()
    try:
        recorded = json.loads((staged / "preview.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackageRefused("The upload record is damaged. Upload the archive again.") from exc
    preview = inspect_archive(data)
    if preview.archive_sha256 != recorded.get("archive_sha256"):
        raise PackageRefused("The archive changed after review. Upload it again.", code="changed")
    if not preview.installable or not preview.module_name:
        raise PackageRefused("The package does not pass the checks.", code="invalid")

    name = preview.module_name
    dir_name = name.removeprefix("oe_")
    root = runtime_modules_dir().expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = root / dir_name
    tmp = None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            tmp = stage_and_extract(zf, prefix="oe_module_zip_")
        shutil.move(str(tmp / dir_name), str(target))
    except (UnsafeArchiveError, OSError) as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise PackageRefused(f"The archive could not be unpacked: {exc}") from exc
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)

    marker = {
        "name": name,
        "version": preview.version,
        "display_name": preview.display_name,
        "author": preview.author,
        "archive_sha256": preview.archive_sha256,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "installed_by": actor,
        "ui": preview.ui,
    }
    (target / MARKER_FILE).write_text(json.dumps(marker, indent=2), encoding="utf-8")

    status = "installed_disabled"
    tables: list[str] = []
    try:
        attach_runtime_root(root, create=False)
        importlib.invalidate_caches()
        module_loader.discover()
        if name not in module_loader._manifests:
            raise PackageRefused("The module was unpacked but its manifest did not load.")
        if enable:
            await module_loader.enable_module(name, app)
            tables = await create_missing_tables(name)
            status = "active"
        else:
            from app.core.module_state import set_module_enabled

            module_loader._disabled.add(name)
            module_loader._manifests[name].enabled = False
            core = {n for n, m in module_loader._manifests.items() if m.category == "core"}
            set_module_enabled(name, False, core_modules=core)
    except Exception as exc:
        with contextlib.suppress(Exception):
            if name in module_loader._modules:
                await module_loader.disable_module(name, app)
        module_loader.forget_module(name)
        shutil.rmtree(target, ignore_errors=True)
        logger.exception("module_package: %s failed to load and was removed", name)
        if isinstance(exc, PackageRefused):
            raise
        raise PackageRefused(f"The module did not load, so it was removed again. {exc}", code="load_failed") from exc
    finally:
        discard(token)

    return {"name": name, "version": preview.version, "status": status, "tables": tables, "ui": preview.ui}


async def uninstall(module_name: str, app: Any) -> dict[str, Any]:
    """Remove a module that was installed from a ZIP. Its database tables are kept.

    Raises:
        PackageRefused: Not a ZIP-installed module, or another module depends on it.
    """
    from app.core.module_loader import module_loader

    if not _NAME_RE.match(module_name):
        raise PackageRefused("Unknown module.", code="not_found")
    target = runtime_modules_dir().expanduser() / module_name.removeprefix("oe_")
    if read_marker(target) is None:
        raise PackageRefused("This module was not installed from a ZIP and cannot be removed here.", code="not_found")
    dependants = [
        n for n, m in module_loader._manifests.items() if module_name in m.depends and module_loader.is_enabled(n)
    ]
    if dependants:
        raise PackageRefused(f"Other modules depend on it: {', '.join(sorted(dependants))}.", code="in_use")
    if module_name in module_loader._modules:
        await module_loader.disable_module(module_name, app)
    module_loader.forget_module(module_name)
    shutil.rmtree(target, ignore_errors=True)
    return {"name": module_name, "status": "removed"}


def ui_entries() -> list[dict[str, Any]]:
    """Hosted UI pages of ZIP-installed modules that are loaded and enabled."""
    from app.core.module_loader import module_loader

    out = []
    for marker in installed_packages():
        name = marker.get("name")
        ui = marker.get("ui")
        if not ui or name not in module_loader._modules or not module_loader.is_enabled(name):
            continue
        out.append({"module": name, **ui})
    return out


def hosted_prefixes() -> list[str]:
    """API prefixes of modules that serve a hosted page, for the iframe CORS rule."""
    out: list[str] = []
    for entry in ui_entries():
        out.extend(module_api_prefixes(entry["module"]))
    return out
