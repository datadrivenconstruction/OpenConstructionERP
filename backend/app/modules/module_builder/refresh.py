# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Render an installed module's code again when the generator has moved on.

The builder never writes into a module directory that exists, so a fix to what
the generator renders reaches modules built afterwards and none of those already
installed. Usually that is the right trade. When the fix closes a hole it is not:
the first generator's router served every project's records to anyone holding
the module's read permission, and a server that installed a module before the
fix would go on doing that until somebody rebuilt it by hand.

So at startup, before any runtime module is imported, every installed module
whose ``spec.json`` names an older generator has its code rendered again from
that spec. The spec is the canonical description; the code is derived from it.

What is replaced and what is not:

* Only the code files in :data:`CODE_FILES`, plus ``spec.json`` for its stamp.
  The original ``generated_at`` is kept, since it says when the module was
  built.
* Never data. Nothing here opens a database connection.
* Never the table definition or the API schema. The files in
  :data:`CONTRACT_FILES` must render byte for byte as they stand on disk. If
  they do not, the module was edited by hand or written by something else, its
  table may not be what this spec describes, and it is left alone with an error
  in the log.
* Never a module whose spec no longer validates. It is left as it is, and the
  log names it.

The swap is a directory rename, not a file-by-file overwrite: a module running
the new router against the old service would fail on its first request. The
previous directory is kept under :data:`WORK_DIR`, so code someone edited by
hand can be recovered; nothing prunes those copies, there is one per module per
generator version. Running this again finds every module current and does
nothing, and a lock keeps two processes starting at once from refreshing the
same root together.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.core.module_runtime_root import runtime_modules_dir
from app.modules.module_builder import generator
from app.modules.module_builder.spec import ModuleSpec

logger = logging.getLogger(__name__)

#: Outcomes, one per installed module directory.
REFRESHED = "refreshed"
CURRENT = "current"
INVALID = "invalid"
REFUSED = "refused"
FAILED = "failed"

#: Staging and backups live here, inside the runtime root so that the swap is a
#: rename on one filesystem. The leading underscore keeps the module loader out
#: of it, and nothing in it sits directly under the root with a ``spec.json``,
#: so the builder's list of installed modules never shows a backup.
WORK_DIR = "_module_builder"

#: What a refresh rewrites, besides ``spec.json``.
CODE_FILES = ("router.py", "repository.py", "service.py")

#: What must already be exactly what the spec renders: the table definition
#: (``models.py``, ``schema.py``) and the request and response schemas the new
#: router and service are written against (``schemas.py``).
CONTRACT_FILES = ("models.py", "schema.py", "schemas.py")

#: How long a second process waits for a refresh already running, and how old a
#: lock has to be before it is taken for one a dead process left. A refresh is
#: a few file copies and two renames, so both are generous.
_LOCK_WAIT_SECONDS = 60.0
_LOCK_STALE_SECONDS = 600.0

_STAMP = re.compile(rf"^{re.escape(generator.GENERATOR_NAME)}/(\d+)$")


def refresh_installed(root: Path | None = None) -> dict[str, str]:
    """Bring every installed module's code up to the current generator.

    Call before the module loader discovers anything, so that no stale router
    has been imported yet. Never raises: a module that cannot be refreshed is
    logged and keeps the code it had.

    Args:
        root: The runtime module root. Defaults to the instance's own.

    Returns:
        The outcome for each installed module, by directory name.
    """
    root = root or runtime_modules_dir()
    work = root / WORK_DIR
    try:
        if not root.is_dir() or not _installed(root):
            # Nothing installed: no lock, no working directory, nothing written.
            return {}
        with _exclusive(work):
            return _refresh_all(root, work)
    except (OSError, TimeoutError):
        logger.exception("module_builder: installed modules were not checked for a code refresh")
        return {}


@contextmanager
def _exclusive(work: Path) -> Iterator[None]:
    """One refresh per runtime root at a time.

    The shipped entry points start one process, but uvicorn starts several when
    ``WEB_CONCURRENCY`` is set, and each runs startup. Two refreshes of one
    directory would clear each other's staging, and a process that skipped
    ahead would import a module mid-swap, when its directory briefly does not
    exist. So a second process waits for the first to finish rather than
    skipping. A lock left by a process that died is broken once it is older
    than any refresh takes.
    """
    work.mkdir(parents=True, exist_ok=True)
    lock = work / "lock"
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                continue  # released between the two calls
            if age > _LOCK_STALE_SECONDS:
                logger.warning("module_builder: breaking a refresh lock left %.0f s ago at %s", age, lock)
                shutil.rmtree(lock, ignore_errors=True)
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"another process has held {lock} for {age:.0f} s") from None
            time.sleep(0.1)
    try:
        yield
    finally:
        shutil.rmtree(lock, ignore_errors=True)


def _refresh_all(root: Path, work: Path) -> dict[str, str]:
    # Whatever an interrupted run left half-written. Never a module: staged
    # copies only become a module by being renamed into place.
    shutil.rmtree(work / "staging", ignore_errors=True)

    outcomes: dict[str, str] = {}
    for directory in _installed(root):
        try:
            outcomes[directory.name] = _refresh_one(directory, work)
        except Exception:
            logger.exception(
                "module_builder: refreshing %s failed unexpectedly; it keeps the code it had", directory.name
            )
            outcomes[directory.name] = FAILED
    return outcomes


def _installed(root: Path) -> list[Path]:
    """Module directories the builder installed: each carries its spec.json."""
    return [
        directory
        for directory in sorted(root.iterdir())
        if directory.is_dir() and not directory.name.startswith(("_", ".")) and (directory / "spec.json").is_file()
    ]


def _refresh_one(target: Path, work: Path) -> str:
    key = target.name

    try:
        payload = json.loads((target / "spec.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error("module_builder: %s has an unreadable spec.json, left untouched: %s", key, exc)
        return INVALID
    if not isinstance(payload, dict):
        logger.error("module_builder: %s has a spec.json that is not an object, left untouched", key)
        return INVALID

    stamp = payload.pop("generator", None)
    match = _STAMP.match(stamp) if isinstance(stamp, str) else None
    if match is None:
        logger.error("module_builder: %s names no generator this platform recognises (%r), left untouched", key, stamp)
        return INVALID
    version = int(match.group(1))
    if version >= generator.GENERATOR_VERSION:
        return CURRENT

    generated_at = payload.pop("generated_at", None)
    try:
        spec = ModuleSpec.model_validate(payload)
    except ValidationError as exc:
        logger.error(
            "module_builder: %s was built by generator %d and its spec no longer validates, so its code "
            "cannot be refreshed and it keeps the old code: %s",
            key,
            version,
            exc,
        )
        return INVALID
    if spec.key != key:
        logger.error("module_builder: %s holds the spec of %r, left untouched", key, spec.key)
        return INVALID

    rendered = {item.path: item.content for item in generator.render(spec)}

    differing = [name for name in CONTRACT_FILES if not _matches(target / name, rendered[name])]
    if differing:
        logger.error(
            "module_builder: %s was not refreshed, because %s on disk differ from what its spec renders. "
            "It was edited by hand or built by something else, so rendering new code over it could "
            "disagree with its table. It keeps the code of generator %d; rebuild it from the builder.",
            key,
            ", ".join(differing),
            version,
        )
        return REFUSED

    files = {name: rendered[name] for name in CODE_FILES}
    files["spec.json"] = _restamped(rendered["spec.json"], generated_at)

    staging = work / "staging" / key
    try:
        shutil.copytree(target, staging, ignore=shutil.ignore_patterns("__pycache__"))
        _write_files(staging, files)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        logger.exception("module_builder: %s could not be staged for refresh; it keeps the old code", key)
        return FAILED

    stamp_now = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = work / "backups" / f"{key}-generator{version}-{stamp_now}"
    backup.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.replace(target, backup)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        logger.exception("module_builder: %s could not be moved aside for refresh; it keeps the old code", key)
        return FAILED

    try:
        os.replace(staging, target)
    except OSError:
        logger.exception("module_builder: %s refreshed code could not be put in place; restoring the old code", key)
        try:
            os.replace(backup, target)
        except OSError:
            logger.critical(
                "module_builder: %s is NOT INSTALLED: its old code is at %s and its new code at %s. "
                "Move either one back to %s by hand.",
                key,
                backup,
                staging,
                target,
            )
            return FAILED
        shutil.rmtree(staging, ignore_errors=True)
        return FAILED

    logger.warning(
        "module_builder: %s code refreshed from generator %d to %d (%s); data and table untouched, "
        "previous code kept at %s",
        key,
        version,
        generator.GENERATOR_VERSION,
        ", ".join(files),
        backup,
    )
    return REFRESHED


def _matches(path: Path, content: str) -> bool:
    try:
        return path.read_bytes() == content.encode("utf-8")
    except OSError:
        return False


def _restamped(rendered_spec: str, generated_at: object) -> str:
    """The freshly rendered spec.json, keeping the date the module was built."""
    payload = json.loads(rendered_spec)
    if isinstance(generated_at, str) and generated_at:
        payload["generated_at"] = generated_at
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _write_files(directory: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        # LF on every platform, as generator.write does.
        (directory / name).write_text(content, encoding="utf-8", newline="\n")
