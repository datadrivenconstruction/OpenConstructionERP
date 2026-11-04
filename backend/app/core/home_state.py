# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Instance state that historically lived under the account's home directory.

Several writers kept persistent state under ``~/.openestimate`` or
``~/.openestimator`` and ignored the operator data dir. In the container image
the service account's home is ``/app``, inside the image layer, so that state
(module enable/disable, the applied pack, meeting signatures, runtime-installed
modules, ...) vanished whenever the container was recreated, while the mounted
``/data`` volume stayed empty.

:func:`home_state_dir` is the one resolver for such paths. When the operator
points the platform at a data dir (``OE_DATA_DIR``, then ``DATA_DIR``) the path
lives below it; otherwise it stays exactly where it always was, so desktop and
pip installs keep reading the files they already have.

``OE_CLI_DATA_DIR`` is deliberately not an operator override here: the desktop
launcher always exports it, and honouring it would move a desktop user's files.

:func:`migrate_legacy_home_state` copies state left under the home directory by
an earlier version into the data dir once, on startup. It never deletes or
overwrites anything.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Variables an operator uses to put instance data on a persistent volume.
OPERATOR_ENV_VARS: tuple[str, ...] = ("OE_DATA_DIR", "DATA_DIR")

#: The current per-user root and the pre-rename one; both still hold data.
HOME_ROOT = ".openestimate"
LEGACY_HOME_ROOT = ".openestimator"

#: Records which legacy entries were already copied, so each copies once.
MIGRATION_MARKER = ".home_state_migrated.json"


def operator_data_dir() -> Path | None:
    """Return the operator data dir, or ``None`` when none is configured.

    Whitespace counts as unset: a compose file spells "not set" as an empty value.
    """
    for name in OPERATOR_ENV_VARS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return Path(raw).expanduser()
    return None


def legacy_home_dir(root: str, *parts: str) -> Path:
    """Return the historical location ``~/<root>/<parts>``."""
    return Path.home().joinpath(root, *parts)


def home_state_dir(root: str, *parts: str) -> Path:
    """Resolve a persistent path that used to live under ``~/<root>``.

    Args:
        root: The historical home root, :data:`HOME_ROOT` or :data:`LEGACY_HOME_ROOT`.
        *parts: Segments below that root, outermost first. They are kept as-is
            below the operator data dir, so ``~/.openestimator/match_images``
            becomes ``$OE_DATA_DIR/match_images``.

    Returns:
        ``<operator data dir>/<parts>`` when an operator data dir is set,
        otherwise ``~/<root>/<parts>``. Nothing is created.
    """
    override = operator_data_dir()
    if override is not None:
        return override.joinpath(*parts)
    return legacy_home_dir(root, *parts)


def home_state_dir_or_legacy(root: str, *parts: str) -> Path:
    """Like :func:`home_state_dir`, but keep using a populated legacy location.

    For large rebuildable data (vector indexes, downloaded cost databases) that
    the one-time migration does not copy: a host that already built it under
    the home directory keeps using it until the data dir holds its own copy.
    """
    resolved = home_state_dir(root, *parts)
    legacy = legacy_home_dir(root, *parts)
    if resolved == legacy or resolved.exists():
        return resolved
    try:
        if legacy.is_dir() and any(legacy.iterdir()):
            return legacy
    except OSError:
        pass
    return resolved


@dataclass(frozen=True)
class LegacyEntry:
    """One file or directory a pre-fix version wrote under the home directory."""

    root: str
    parts: tuple[str, ...]

    @property
    def key(self) -> str:
        """Stable identifier stored in the migration marker."""
        return "/".join((self.root, *self.parts))


#: User data and configuration worth carrying over. Downloadable binaries
#: (converters, embedding models), rebuildable indexes and caches, and
#: in-flight upload chunks are left out: they are fetched or rebuilt on demand.
LEGACY_ENTRIES: tuple[LegacyEntry, ...] = (
    LegacyEntry(HOME_ROOT, ("module_states.json",)),
    LegacyEntry(HOME_ROOT, ("pack_state.json",)),
    LegacyEntry(HOME_ROOT, ("partner_pack_state.json",)),
    LegacyEntry(HOME_ROOT, ("translations",)),
    LegacyEntry(LEGACY_HOME_ROOT, ("meetings", "signatures")),
    LegacyEntry(LEGACY_HOME_ROOT, ("uploads",)),
    LegacyEntry(LEGACY_HOME_ROOT, ("match_images",)),
    LegacyEntry(LEGACY_HOME_ROOT, ("modules",)),
)


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


def _copy_missing(source: Path, target: Path) -> int:
    """Copy every file of ``source`` that ``target`` lacks; return how many."""
    if source.is_file():
        if target.exists():
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return 1
    copied = 0
    for dirpath, _dirnames, filenames in os.walk(source):
        rel = Path(dirpath).relative_to(source)
        for filename in filenames:
            destination = target / rel / filename
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(dirpath) / filename, destination)
            copied += 1
    return copied


def _read_marker(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    done = data.get("migrated") if isinstance(data, dict) else None
    return {str(item) for item in done} if isinstance(done, list) else set()


def migrate_legacy_home_state(entries: tuple[LegacyEntry, ...] = LEGACY_ENTRIES) -> list[str]:
    """Copy state an earlier version left under the home dir into the data dir.

    Runs only when an operator data dir is set. Each entry is copied once
    (tracked in :data:`MIGRATION_MARKER` inside the data dir); a file already
    present in the data dir is never overwritten, and the legacy copy is never
    deleted. Failures are logged and retried on the next start.

    Args:
        entries: The legacy locations to consider.

    Returns:
        The keys of the entries copied by this call.
    """
    target_root = operator_data_dir()
    if target_root is None:
        return []
    marker = target_root / MIGRATION_MARKER
    done = _read_marker(marker)
    migrated: list[str] = []
    for entry in entries:
        if entry.key in done:
            continue
        source = legacy_home_dir(entry.root, *entry.parts)
        target = target_root.joinpath(*entry.parts)
        try:
            if not source.exists() or _same_path(source, target):
                continue
            copied = _copy_missing(source, target)
        except OSError:
            logger.warning("Could not copy legacy %s to %s; will retry on next start", source, target, exc_info=True)
            continue
        logger.info("Copied %d legacy file(s) from %s to %s (original kept)", copied, source, target)
        done.add(entry.key)
        migrated.append(entry.key)
    if migrated:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"migrated": sorted(done)}, indent=2), encoding="utf-8")
        except OSError:
            logger.warning("Could not record legacy home-state migration in %s", marker, exc_info=True)
    return migrated
