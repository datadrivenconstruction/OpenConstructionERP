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

* The code files in :data:`CODE_FILES` and the module's own test file, plus
  ``spec.json`` for its stamp. The original ``generated_at`` is kept, since it
  says when the module was built.
* Never data. Nothing here opens a database connection.
* Never the table definition or the API schema. The files in
  :data:`CONTRACT_FILES` must render as they stand on disk: byte for byte, or
  differing only inside docstrings, which is where generator 3 started
  escaping names. Such a file is rewritten, since it says nothing different.
  Any other difference means the module was edited by hand or written by
  something else, its table may not be what this spec describes, and it is
  left alone with an error in the log.
* The manifest only when it holds statements its render does not.
* Never a module whose spec no longer validates. It is left as it is, and the
  log names it.

Up to generator 2 a name went into the code unescaped, so a name holding a
quote could end the docstring or string it was written into and put code of
its own in the module. Such a module must not be imported again, and the old
code cannot be told apart from a careful hand edit by looking at it alone. So
for a module built before generator 3:

* a contract file holding statements the render lacks, or
* a spec with a quote, a backslash or a control character in it whose code
  cannot be rendered again in full (the spec no longer validates, a contract
  file differs, or the swap fails)

puts the module in quarantine: its directory moves under
``_module_builder/quarantine``, where the loader never looks, with a note
saying why. Its records are untouched. The builder lists it as switched off,
and it can be removed or built again from there.

The swap is a directory rename, not a file-by-file overwrite: a module running
the new router against the old service would fail on its first request. The
previous directory is kept under :data:`WORK_DIR`, so code someone edited by
hand can be recovered; nothing prunes those copies, there is one per module per
generator version. Running this again finds every module current and does
nothing, and a lock keeps two processes starting at once from refreshing the
same root together.
"""

from __future__ import annotations

import ast
import copy
import json
import logging
import os
import re
import shutil
import time
import unicodedata
import warnings
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
QUARANTINED = "quarantined"

#: Staging and backups live here, inside the runtime root so that the swap is a
#: rename on one filesystem. The leading underscore keeps the module loader out
#: of it, and nothing in it sits directly under the root with a ``spec.json``,
#: so the builder's list of installed modules never shows a backup.
WORK_DIR = "_module_builder"

#: Modules that must not be loaded, one directory per key, under WORK_DIR.
QUARANTINE_DIR = "quarantine"
#: Written into a quarantined module's directory: why it is there.
QUARANTINE_NOTE = "quarantine.json"

#: Why a module was quarantined, as the builder's list reports it.
UNSAFE_CODE = "unsafe_code"
UNVERIFIABLE = "unverifiable"

#: The first generator that escapes names. Modules from before it are checked.
ESCAPED_SINCE = 3

#: What a refresh rewrites, besides ``spec.json`` and the module's test file.
#: None of it describes the table or the API, and all of it held names.
CODE_FILES = ("__init__.py", "permissions.py", "validators.py", "repository.py", "service.py", "router.py")

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
    logged and keeps the code it had, unless that code may hold what a name
    put there, in which case it is quarantined and not loaded.

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
        _set_aside_exposed(root)
        return {}


def _set_aside_exposed(root: Path) -> None:
    """Keep the loader off modules a name may have put code into, when the refresh could not run.

    The loader runs next either way. Every other module keeps loading the code
    it has, as it would have without a refresh; one built before generator 3
    with a name that could have left its literal is quarantined unchecked, or,
    if even that fails, renamed with a leading underscore in place.
    """
    try:
        candidates = _installed(root)
    except OSError:
        logger.critical("module_builder: the runtime module folder %s cannot be read", root, exc_info=True)
        return
    for directory in candidates:
        version, payload = _stamp_of(directory)
        if version is None or version >= ESCAPED_SINCE or not could_break_out(payload):
            continue
        outcome = _quarantine(directory, root / WORK_DIR, version, UNVERIFIABLE, {}, "its code could not be checked")
        if outcome == QUARANTINED or not directory.exists():
            continue
        aside = root / f"_unchecked_{directory.name}"
        try:
            os.replace(directory, aside)
        except OSError:
            logger.critical(
                "module_builder: %s may hold code a name put there and could not be set aside; it WILL be loaded. "
                "Move %s out of the module folder by hand.",
                directory.name,
                directory,
                exc_info=True,
            )
            continue
        logger.error(
            "module_builder: %s was NOT loaded: it may hold code a name put there and could not be checked. "
            "It is at %s with its records untouched; build it again from the module builder.",
            directory.name,
            aside,
        )


def _stamp_of(directory: Path) -> tuple[int | None, dict[str, Any]]:
    """The generator version a module was built by, and its spec payload."""
    try:
        payload = json.loads((directory / "spec.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}
    if not isinstance(payload, dict):
        return None, {}
    stamp = payload.get("generator")
    match = _STAMP.match(stamp) if isinstance(stamp, str) else None
    return (int(match.group(1)) if match else None), payload


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

    # Whether a name could have put code into this module. Only then does code
    # that cannot be rendered again stop the module from loading.
    exposed = version < ESCAPED_SINCE and could_break_out(payload)

    generated_at = payload.pop("generated_at", None)
    try:
        spec = ModuleSpec.model_validate(payload)
    except ValidationError as exc:
        if exposed:
            return _quarantine(target, work, version, UNVERIFIABLE, {}, f"its spec no longer validates: {exc}")
        logger.error(
            "module_builder: %s was built by generator %d and its spec no longer validates, so its code "
            "cannot be refreshed and it keeps the old code: %s",
            key,
            version,
            exc,
        )
        return INVALID
    if spec.key != key:
        if exposed:
            return _quarantine(target, work, version, UNVERIFIABLE, {}, f"it holds the spec of {spec.key!r}")
        logger.error("module_builder: %s holds the spec of %r, left untouched", key, spec.key)
        return INVALID

    rendered = {item.path: item.content for item in generator.render(spec)}

    stale: list[str] = []
    differing: list[str] = []
    for name in CONTRACT_FILES:
        on_disk = _read(target / name)
        wanted = rendered[name].encode("utf-8")
        if on_disk == wanted:
            continue
        if on_disk is not None and same_apart_from_docstrings(on_disk, wanted):
            stale.append(name)
        else:
            differing.append(name)

    if version < ESCAPED_SINCE:
        unsafe = [name for name in differing if adds_code(_read(target / name), rendered[name])]
        if unsafe:
            return _quarantine(
                target, work, version, UNSAFE_CODE, {"files": unsafe}, "it holds code its spec does not render"
            )
    if differing:
        if exposed:
            return _quarantine(
                target,
                work,
                version,
                UNVERIFIABLE,
                {},
                f"{', '.join(differing)} differ from what its spec renders, so its code cannot be rendered again",
            )
        logger.error(
            "module_builder: %s was not refreshed, because %s on disk differ from what its spec renders. "
            "It was edited by hand or built by something else, so rendering new code over it could "
            "disagree with its table. It keeps the code of generator %d; rebuild it from the builder.",
            key,
            ", ".join(differing),
            version,
        )
        return REFUSED

    files = {name: rendered[name] for name in (*CODE_FILES, f"tests/test_{key}.py", *stale)}
    # The manifest carries no route and no query, so a difference there is not
    # a reason to touch it. Statements its render does not have are.
    if version < ESCAPED_SINCE and adds_code(_read(target / "manifest.py"), rendered["manifest.py"]):
        files["manifest.py"] = rendered["manifest.py"]
    files["spec.json"] = _restamped(rendered["spec.json"], generated_at)

    outcome = _swap(target, work, version, files)
    if outcome == FAILED and exposed and target.is_dir():
        return _quarantine(target, work, version, UNVERIFIABLE, {}, "its code could not be rendered again")
    return outcome


def _swap(target: Path, work: Path, version: int, files: dict[str, str]) -> str:
    """Put *files* in place of the module's own, as one rename."""
    key = target.name
    staging = work / "staging" / key
    try:
        shutil.copytree(target, staging, ignore=shutil.ignore_patterns("__pycache__"))
        _write_files(staging, files)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        logger.exception("module_builder: %s could not be staged for refresh; it keeps the old code", key)
        return FAILED

    backup = _backup_path(work, f"{key}-generator{version}")

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


def _backup_path(work: Path, name: str) -> Path:
    stamp_now = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = work / "backups" / f"{name}-{stamp_now}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    return backup


def _quarantine(target: Path, work: Path, version: int, code: str, params: dict[str, Any], why: str) -> str:
    """Move a module the loader must not import out of its reach.

    The data stays: nothing here opens a database connection, and the table is
    what the person recorded with the module. Only the code is set aside.
    """
    key = target.name
    place = quarantine_dir(work.parent) / key
    try:
        if place.exists():
            # An earlier quarantine of the same key, since built again and
            # quarantined again. Kept, like every other copy this module set aside.
            os.replace(place, _backup_path(work, f"{key}-quarantined"))
        place.parent.mkdir(parents=True, exist_ok=True)
        os.replace(target, place)
    except OSError:
        logger.critical(
            "module_builder: %s must not be loaded (%s), but could not be moved out of the module folder. "
            "Remove %s by hand before the next start.",
            key,
            why,
            target,
            exc_info=True,
        )
        return FAILED
    note = {
        "code": code,
        "params": params,
        "generator": version,
        "quarantined_at": datetime.now(UTC).isoformat(),
    }
    try:
        (place / QUARANTINE_NOTE).write_text(json.dumps(note, indent=2) + "\n", encoding="utf-8", newline="\n")
    except OSError:
        logger.warning("module_builder: %s quarantine note could not be written", key, exc_info=True)
    files = params.get("files") or []
    logger.error(
        "module_builder: %s was NOT loaded and is quarantined at %s, because %s%s. Its records are "
        "untouched; remove it or build it again from the module builder.",
        key,
        place,
        why,
        f" ({', '.join(files)})" if files else "",
    )
    return QUARANTINED


def quarantine_dir(root: Path) -> Path:
    """Where quarantined modules of the runtime root *root* are kept."""
    return root / WORK_DIR / QUARANTINE_DIR


def quarantined(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every quarantined module directory with its note, by key."""
    place = quarantine_dir(root)
    if not place.is_dir():
        return []
    found = []
    for directory in sorted(place.iterdir()):
        if not directory.is_dir():
            continue
        try:
            note = json.loads((directory / QUARANTINE_NOTE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            note = {}
        found.append((directory, note if isinstance(note, dict) else {}))
    return found


# ── telling code a name put there from code the spec renders ───────────────

# What could end the string or comment a name was written into. A name without
# any of them stayed inside it under every generator.
_BREAKS_OUT = frozenset('"\\')
_BREAKS_OUT_CATEGORIES = frozenset({"Cc", "Cs", "Zl", "Zp"})


def could_break_out(value: Any) -> bool:
    """Whether any text in a spec payload could have left the literal it was rendered into."""
    if isinstance(value, str):
        return any(c in _BREAKS_OUT or unicodedata.category(c) in _BREAKS_OUT_CATEGORIES for c in value)
    if isinstance(value, dict):
        return any(could_break_out(k) or could_break_out(v) for k, v in value.items())
    if isinstance(value, list):
        return any(could_break_out(v) for v in value)
    return False


def same_apart_from_docstrings(installed: bytes, rendered: bytes) -> bool:
    """Whether two sources differ only inside their docstrings.

    Compared as text with every docstring blanked, so a comment, a format
    change or any statement still counts as a difference.
    """
    left = _without_docstrings(installed)
    return left is not None and left == _without_docstrings(rendered)


def _without_docstrings(source: bytes) -> bytes | None:
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError):
        return None
    starts = [0]
    for line in source.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            value = first.value
            if value.end_lineno is None or value.end_col_offset is None or value.end_lineno > len(starts) - 1:
                return None
            # Offsets are in UTF-8 bytes, as the source is.
            spans.append(
                (starts[value.lineno - 1] + value.col_offset, starts[value.end_lineno - 1] + value.end_col_offset)
            )
    for begin, end in sorted(spans, reverse=True):
        source = source[:begin] + b'""' + source[end:]
    return source


def adds_code(installed: bytes | None, rendered: str) -> bool:
    """Whether *installed* holds statements that *rendered* does not.

    Every statement at every depth is reduced to what it does, not what text it
    carries: a docstring is a docstring whatever it says, an assignment is its
    target and the kind of value, a call is what it calls. A name that broke out
    of its literal shows up as a statement the render does not have, or as a
    docstring turned into an expression. A file Python cannot parse adds
    nothing: it cannot be imported, so none of it runs.
    """
    if installed is None:
        return False
    try:
        mine = Counter(_statements(_parse(installed)))
    except (SyntaxError, ValueError):
        return False
    return bool(mine - Counter(_statements(_parse(rendered))))


def _parse(source: bytes | str) -> ast.Module:
    # Old docstrings hold unescaped backslashes; reading them is not the place
    # to warn about it, at every start.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source)


def _statements(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                yield "doc"
            else:
                yield f"expr {_shape(node.value)}"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            yield ast.dump(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield f"{type(node).__name__} {node.name}"
        elif isinstance(node, ast.Assign):
            yield f"assign {[ast.dump(t) for t in node.targets]} {_value(node.value)}"
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            yield f"{type(node).__name__} {ast.dump(node.target)} {_value(node.value)}"
        else:
            yield type(node).__name__


def _value(node: ast.AST | None) -> str:
    if isinstance(node, ast.Call):
        return f"call {_shape(node.func)}"
    return type(node).__name__


def _shape(node: ast.AST) -> str:
    """An expression with the text of its string constants left out."""
    blank = copy.deepcopy(node)
    for inner in ast.walk(blank):
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            inner.value = ""
    return ast.dump(blank)


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _restamped(rendered_spec: str, generated_at: object) -> str:
    """The freshly rendered spec.json, keeping the date the module was built."""
    payload = json.loads(rendered_spec)
    if isinstance(generated_at, str) and generated_at:
        payload["generated_at"] = generated_at
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _write_files(directory: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # LF on every platform, as generator.write does.
        path.write_text(content, encoding="utf-8", newline="\n")
