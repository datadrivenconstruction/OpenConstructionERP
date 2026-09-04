# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A second home for modules, outside the source tree.

Modules that ship with the platform live in ``backend/app/modules``. Modules a
user installs at runtime must not, for two reasons that both bite in
production: a platform upgrade replaces the source tree and would take the
user's modules with it, and an operator running a packaged build has no source
tree to write into at all.

So installed modules live in the instance's own data directory, and this module
teaches the import system to look there as well.

The mechanism is the package ``__path__``. ``ModuleLoader`` imports modules by
package path (``importlib.import_module("app.modules.boq.manifest")``), so
appending the runtime directory to ``app.modules.__path__`` makes every
downstream consumer - the loader, the plugin manager, router mounting, Alembic
model discovery - find runtime modules with no change of their own.

Appended, never prepended. Import resolution walks ``__path__`` in order, so a
shipped module always wins a name collision and no installed package can
shadow ``app.modules.projects`` with its own. A collision is reported rather
than ignored, because the installed copy is then dead code that its author
believes is running.

Usage::

    from app.core.module_runtime_root import attach_runtime_root
    attach_runtime_root()          # once, at startup, before discover()
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# The package whose search path gains a second entry.
_PACKAGE = "app.modules"

# Environment override, for operators who keep instance data somewhere else.
ENV_VAR = "OE_RUNTIME_MODULES_DIR"

# Where installed modules live when nothing overrides it. Same instance home as
# the rest of the platform's writable state (uploads, vectors, CWICR indexes).
DEFAULT_SUBPATH = (".openestimator", "modules")


def default_runtime_modules_dir() -> Path:
    """The built-in location for installed modules, ignoring any override."""
    return Path.home().joinpath(*DEFAULT_SUBPATH)


def runtime_modules_dir() -> Path:
    """Resolve where installed modules live.

    Order: the ``OE_RUNTIME_MODULES_DIR`` environment variable, then the
    instance home. The path is returned whether or not it exists - creating it
    is :func:`attach_runtime_root`'s job, so that a read-only caller asking
    where modules go does not have the side effect of making the directory.
    """
    override = (os.environ.get(ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return default_runtime_modules_dir()


def _package_path() -> list[str]:
    """The live ``__path__`` list of ``app.modules``.

    Imported on demand rather than at module import time: this file is imported
    by application startup, and reaching into ``app.modules`` from the top level
    would fix the import order of two packages that do not otherwise depend on
    each other.
    """
    package = importlib.import_module(_PACKAGE)
    path = getattr(package, "__path__", None)
    if not isinstance(path, list):
        # A namespace package exposes _NamespacePath, which supports append but
        # is not a list. app.modules ships an __init__.py so this should not
        # happen; if it ever does, say so rather than mutating something whose
        # semantics we have not checked.
        raise TypeError(f"{_PACKAGE}.__path__ is {type(path).__name__}, expected list")
    return path


def module_search_paths() -> list[Path]:
    """Every directory ``app.modules`` is searched in, in import order.

    Entry zero is the shipped root; anything after it was attached at runtime.
    """
    return [Path(p) for p in _package_path()]


def runtime_root_paths() -> list[Path]:
    """Every search root currently attached beyond the shipped one."""
    path = _package_path()
    return [Path(p) for p in path[1:]]


def is_attached(directory: Path | None = None) -> bool:
    """Whether ``directory`` (default: the resolved runtime dir) is on the path."""
    target = (directory or runtime_modules_dir()).expanduser()
    return any(same_dir(Path(p), target) for p in _package_path())


def attach_runtime_root(directory: Path | None = None, *, create: bool = True) -> Path | None:
    """Make installed modules importable as ``app.modules.<name>``.

    Args:
        directory: Where installed modules live. Defaults to
            :func:`runtime_modules_dir`.
        create: Create the directory when it does not exist. A missing
            directory is the normal state of a fresh instance, and an import
            root that does not exist is harmless but also useless, so the
            default is to make it.

    Returns:
        The attached directory, or ``None`` when there was nothing to attach
        (the directory does not exist and ``create`` is False).

    Calling this more than once is safe and does nothing the second time.
    """
    target = (directory or runtime_modules_dir()).expanduser()

    if not target.exists():
        if not create:
            logger.info("Runtime module root does not exist, not attaching: %s", target)
            return None
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            # A read-only or unwritable instance home is a deployment fact, not
            # a crash: the platform runs perfectly well with only its shipped
            # modules, so this degrades rather than fails.
            logger.exception("Could not create the runtime module root: %s", target)
            return None

    path = _package_path()
    if any(same_dir(Path(p), target) for p in path):
        return target

    path.append(str(target))
    logger.info("Runtime module root attached: %s", target)
    _report_shadowed(target)
    return target


def detach_runtime_root(directory: Path) -> bool:
    """Remove a root from the search path. Returns whether anything was removed.

    The shipped root is never removed: it is entry zero and removing it would
    leave the platform unable to import its own modules.
    """
    target = directory.expanduser()
    path = _package_path()
    for index in range(len(path) - 1, 0, -1):
        if same_dir(Path(path[index]), target):
            del path[index]
            logger.info("Runtime module root detached: %s", target)
            return True
    return False


def origin_of(module_dir_name: str) -> str | None:
    """Where a module directory was found: ``"shipped"``, ``"runtime"``, or None.

    Resolution order, so the answer matches what Python will actually import
    rather than merely where a directory happens to exist.
    """
    for index, entry in enumerate(_package_path()):
        if (Path(entry) / module_dir_name).is_dir():
            return "shipped" if index == 0 else "runtime"
    return None


def shadowed_modules(directory: Path | None = None) -> list[str]:
    """Directory names in ``directory`` that a shipped module already claims.

    These are installed, look installed, and will never be imported, because
    the shipped root is searched first. Naming them is the whole point: the
    alternative is an author whose module is silently not the one running.
    """
    target = (directory or runtime_modules_dir()).expanduser()
    if not target.is_dir():
        return []
    path = _package_path()
    if not path:
        return []
    shipped = Path(path[0])
    names = []
    for child in sorted(target.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        if (shipped / child.name).is_dir():
            names.append(child.name)
    return names


def _report_shadowed(directory: Path) -> None:
    for name in shadowed_modules(directory):
        logger.warning(
            "Installed module %r is shadowed by a module of the same name that ships with "
            "the platform, and will never be imported. Rename the installed one.",
            name,
        )


def same_dir(left: Path, right: Path) -> bool:
    """Compare two directories as the filesystem would.

    ``Path.samefile`` is the honest comparison - it sees through symlinks, and
    on Windows it sees through case differences and short 8.3 names, both of
    which make two spellings of one directory compare unequal as strings. It
    needs both paths to exist, so string comparison of the resolved forms is
    the fallback for a root that has not been created yet.
    """
    try:
        return left.samefile(right)
    except OSError:
        try:
            return left.expanduser().resolve() == right.expanduser().resolve()
        except OSError:
            return str(left) == str(right)
