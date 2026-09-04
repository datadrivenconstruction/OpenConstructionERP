# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drafting, previewing, installing and removing a generated module.

The assistant's only job here is to turn a sentence into a
:class:`~app.modules.module_builder.spec.ModuleSpec`. It does not write code,
and there is no path by which anything it produces reaches disk except through
the deterministic renderer, from a spec that passed validation. A draft that
describes something impossible fails in the spec and never becomes a file.

With no assistant configured the wizard collects the same structure by hand and
everything below this line behaves identically.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.module_runtime_root import attach_runtime_root, runtime_modules_dir
from app.core.permissions import permission_registry
from app.modules.module_builder import generator
from app.modules.module_builder.spec import ModuleSpec, url_prefix_for

logger = logging.getLogger(__name__)

MAX_DESCRIPTION = 4000

SYSTEM_PROMPT = """\
You describe one module for a construction cost management platform.

You never write code. You return a single JSON object describing the module,
and a deterministic generator turns that description into the module. If the
description cannot be expressed in the schema below, return the closest thing
that can be, rather than inventing fields the schema does not have.

Return JSON only. No prose, no markdown fence.

{
  "key": "snake_case, 3 or more characters, the module's folder name",
  "display_name": "what a person reads",
  "description": "one sentence on what the module is for",
  "category": "community",
  "icon": "a lucide icon name, for example Boxes, HardHat, Truck, ClipboardList",
  "entity": {
    "name": "snake_case singular name of the record, for example hire",
    "display_name": "Hire",
    "plural_name": "Hires",
    "project_scoped": true,
    "fields": [
      {
        "name": "snake_case, never id, project_id, created_at, updated_at or metadata",
        "label": "what a person reads",
        "type": "text | long_text | integer | number | money | date | datetime | boolean | select",
        "required": true,
        "unit": "m2, m3, hours, empty when not a measurement",
        "options": ["only for select, two or more"],
        "in_list": true
      }
    ]
  },
  "rules": [
    {
      "code": "UPPER_SNAKE_CASE",
      "message": "what the person reading it should do about it",
      "kind": "required | positive | not_future | range | one_of | order",
      "field": "the field it is about",
      "other_field": "only for order: this field must not be later than that one",
      "min_value": 0,
      "max_value": 100,
      "severity": "error | warning"
    }
  ]
}

Rules that must hold or the module is refused:
- positive and range apply only to integer, number or money fields.
- one_of applies only to a select field.
- not_future applies only to a date or datetime field.
- order compares two date or datetime fields and they must differ.
- every rule names a field that exists.
- at least one rule. A module with no validation rules is not accepted.

Prefer money over number for anything priced. Prefer select over text where the
answer is one of a known few. Between six and twelve fields is usually right.
Write messages a site engineer would understand, not error codes in prose.
"""


class DraftRefused(Exception):
    """The assistant answered, but not with a module this platform can build."""

    def __init__(self, reason: str, raw: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw = raw


class InstallRefused(Exception):
    """Installation stopped before anything was changed, or was undone."""


@dataclass(frozen=True)
class InstalledModule:
    """What is on disk under the runtime root, as far as the builder can tell."""

    key: str
    module_name: str
    display_name: str
    version: str
    directory: Path
    generated_at: str
    entity: str
    field_count: int
    rule_count: int
    # Where its router is mounted. Carried rather than derived by the caller:
    # the frontend renders a generated module from this path, and the rule that
    # turns a key into a URL belongs to the loader, not to the screen.
    base_path: str


async def draft_spec(session: Any, user_id: str, description: str) -> ModuleSpec:
    """Ask the configured assistant to describe a module, and validate the answer.

    Args:
        session: Database session, used to read the user's AI settings.
        user_id: The user asking, whose provider and key are used.
        description: What they want, in their own words.

    Returns:
        A validated spec. Nothing has been written anywhere.

    Raises:
        DraftRefused: No assistant is configured, it did not return JSON, or
            what it returned does not describe a module that can be built.
    """
    description = (description or "").strip()
    if len(description) < 10:
        raise DraftRefused("Describe the module in a sentence or two so there is something to work from.")
    if len(description) > MAX_DESCRIPTION:
        raise DraftRefused(f"That description is longer than {MAX_DESCRIPTION} characters.")

    from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
    from app.modules.ai.repository import AISettingsRepository

    settings = await AISettingsRepository(session).get_by_user_id(uuid.UUID(user_id))
    try:
        provider, api_key, model = resolve_provider_key_model(settings)
    except ValueError as exc:
        # Not an error the user should have to read as a stack trace: it means
        # no provider is connected, and the wizard's by-hand path still works.
        raise DraftRefused(f"No assistant is connected, so a module cannot be drafted from a sentence. {exc}") from exc

    text, tokens = await call_ai(
        provider,
        api_key,
        SYSTEM_PROMPT,
        description,
        max_tokens=4096,
        model=model,
    )
    logger.info("module_builder: drafted a spec with %s, %s tokens", provider, tokens)

    payload = extract_json(text)
    if not isinstance(payload, dict):
        raise DraftRefused("The assistant did not return a module description.", raw=text[:2000])
    spec = spec_from_payload(payload)
    # Recorded here rather than in spec_from_payload, which also validates
    # payloads that no model produced, and rather than in the router, so that
    # the claim is made by the code that actually called the model. The model
    # does not get to say this about itself: whatever it puts in the field is
    # replaced.
    return spec.model_copy(update={"drafted_by": "assistant"})


def spec_from_payload(payload: dict[str, Any]) -> ModuleSpec:
    """Validate a draft into a spec, with a message a person can act on."""
    try:
        return ModuleSpec.model_validate(payload)
    except ValidationError as exc:
        raise DraftRefused(_readable(exc), raw=json.dumps(payload)[:2000]) from exc


def _readable(exc: ValidationError) -> str:
    """Pydantic's error list, as one sentence per problem.

    The raw form names locations like ``entity.fields.3.name``, which is right
    for a developer and unreadable in a wizard.
    """
    parts = []
    for error in exc.errors()[:6]:
        where = ".".join(str(p) for p in error.get("loc", ()) if p != "__root__")
        message = error.get("msg", "").removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return " ".join(parts) or "That description does not make a module this platform can build."


def preview(spec: ModuleSpec) -> list[dict[str, Any]]:
    """Render the module without writing it, so it can be read before it lands."""
    return [{"path": f.path, "lines": f.lines, "content": f.content} for f in generator.render(spec)]


async def install(spec: ModuleSpec, app: Any) -> InstalledModule:
    """Write the module into the runtime root and load it into the running app.

    Installation is one step from the user's side and has to be one step here
    too: a module whose files landed but which never loaded is invisible and
    still occupies its key. Anything that fails after the write takes the
    directory with it.

    Raises:
        InstallRefused: The key is taken, or the module failed to load.
    """
    root = runtime_modules_dir()
    target = root / spec.key
    if target.exists():
        raise InstallRefused(
            f"A module called {spec.key!r} is already installed. Remove it first, or choose another name."
        )

    root.mkdir(parents=True, exist_ok=True)
    generator.write(spec, root)
    # The root may not have been on the import path yet: on a server where no
    # module has ever been installed the directory did not exist at startup.
    attach_runtime_root(root, create=False)

    try:
        await _load_into(app, spec)
    except Exception as exc:
        shutil.rmtree(target, ignore_errors=True)
        _forget(spec.key)
        # _load_into ran discover() before the load failed, so the registry has
        # already recorded a module whose directory is now gone. Same reason as
        # in uninstall(): an entry with no files behind it is listed, counted
        # and enable-able.
        from app.core.module_loader import module_loader

        module_loader.forget_module(spec.module_name)
        logger.exception("module_builder: %s failed to load and was removed", spec.key)
        raise InstallRefused(f"The module was built but did not load, so it was removed again. {exc}") from exc

    logger.info("module_builder: installed %s at %s", spec.module_name, target)
    return _from_spec(spec, target)


async def _load_into(app: Any, spec: ModuleSpec) -> dict[str, Any]:
    """Discover the new module and mount it, without restarting the server."""
    import importlib

    from app.core.module_loader import module_loader

    # A directory created after this process started is invisible to the import
    # system until its caches are dropped.
    importlib.invalidate_caches()
    module_loader.discover()
    return await module_loader.enable_module(spec.module_name, app)


async def uninstall(key: str, app: Any, *, drop_data: bool = False) -> dict[str, Any]:
    """Take a generated module away again, in one step.

    Args:
        key: The module's directory name.
        app: The running application, so its routes come down with it.
        drop_data: Whether to drop the module's table as well. Off by default:
            removing a module the user regrets installing should not also
            remove what they recorded with it.

    Raises:
        InstallRefused: The key names nothing the builder installed. A module
            that ships with the platform is never removable this way.
    """
    root = runtime_modules_dir()
    target = root / key
    if not target.is_dir():
        raise InstallRefused(f"No module called {key!r} is installed in the runtime module folder.")

    module_name = f"oe_{key}"
    dropped = False
    if drop_data:
        dropped = await _drop_table(key)

    from app.core.module_loader import module_loader

    try:
        await module_loader.disable_module(module_name, app)
    except Exception:
        # The files still have to go: a module left on disk keeps its key and
        # the user cannot install a replacement.
        logger.warning("module_builder: %s did not unload cleanly", module_name, exc_info=True)

    shutil.rmtree(target, ignore_errors=True)
    _forget(key)
    # And out of the module registry. disable_module deliberately keeps the
    # manifest, because that is what a later enable reads back - but the files
    # are gone now, so what it keeps is an entry for a module that cannot be
    # loaded again. Left there it is still listed by /api/v1/modules, still
    # counted by the health endpoint, and still accepted by the enable route,
    # whose 404 guard is a lookup in that same registry; the enable then dies
    # inside importlib instead of answering 404.
    module_loader.forget_module(module_name)
    # The module's permissions go with it. Left registered they would still be
    # listed in the admin matrix and still granted to roles, with no endpoint
    # behind them, and a reinstall from a different spec would inherit them.
    permission_registry.unregister_module_permissions(key)
    logger.info("module_builder: removed %s, data dropped: %s", module_name, dropped)
    return {"key": key, "module_name": module_name, "removed": True, "data_dropped": dropped}


async def _drop_table(key: str) -> bool:
    """Drop the module's own table. Never touches anything else."""
    import importlib

    from app.database import engine

    try:
        schema = importlib.import_module(f"app.modules.{key}.schema")
    except Exception:
        logger.warning("module_builder: %s has no schema module, leaving the data alone", key, exc_info=True)
        return False
    await schema.remove_table(engine)
    return True


def _forget(key: str) -> None:
    """Drop the module's imports, tables and mappers so a reinstall gets the new code.

    Clearing ``sys.modules`` is not enough on its own. Declaring a model also
    registers its table on the shared ``MetaData`` and its class in the mapper
    registry, and both outlive the import. Re-importing a module that declares
    the same table then raises ``InvalidRequestError`` and the install fails,
    so without this a key could be installed once per process and a user
    correcting a field would have to restart the server.

    Only the classes declared by this module's own ``models`` are touched. The
    module is asked which tables it owns rather than being guessed at by name
    prefix, because a key is free to start with another key.
    """
    import importlib
    import sys

    from app.database import Base

    prefix = f"app.modules.{key}"
    models = sys.modules.get(f"{prefix}.models")
    for attr in list(vars(models).values()) if models is not None else []:
        table = getattr(attr, "__table__", None)
        if table is None or getattr(attr, "__module__", "") != f"{prefix}.models":
            continue
        if Base.metadata.tables.get(table.name) is table:
            Base.metadata.remove(table)
        # Removes the name from the declarative class registry, and copes with
        # the case where two classes share a name, which a plain pop does not.
        Base.registry._dispose_cls(attr)

    for name in [n for n in list(sys.modules) if n == prefix or n.startswith(f"{prefix}.")]:
        del sys.modules[name]
    importlib.invalidate_caches()


def installed() -> list[InstalledModule]:
    """Every generated module under the runtime root, newest description first."""
    root = runtime_modules_dir()
    if not root.is_dir():
        return []
    found = [_from_disk(child) for child in sorted(root.iterdir()) if (child / "spec.json").is_file()]
    return [item for item in found if item is not None]


def _from_disk(directory: Path) -> InstalledModule | None:
    """Read a module's own spec.json back: the description its code came from."""
    path = directory / "spec.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A module whose description cannot be read is still installed and
        # still serving. It is left out of the list rather than reported as
        # something it is not, and the directory name says which one it was.
        logger.warning("module_builder: %s has an unreadable spec.json", directory.name)
        return None
    if not isinstance(payload, dict):
        return None

    entity = payload.get("entity") or {}
    key = payload.get("key") or directory.name
    return InstalledModule(
        key=key,
        module_name=f"oe_{key}",
        display_name=payload.get("display_name") or directory.name,
        version=payload.get("version") or "0.0.0",
        directory=directory,
        generated_at=payload.get("generated_at") or "",
        entity=entity.get("display_name") or "",
        field_count=len(entity.get("fields") or []),
        rule_count=len(payload.get("rules") or []),
        base_path=url_prefix_for(key),
    )


def _from_spec(spec: ModuleSpec, directory: Path) -> InstalledModule:
    """Describe what was just installed, from the spec rather than by re-reading it."""
    generated_at = ""
    on_disk = _from_disk(directory)
    if on_disk is not None:
        generated_at = on_disk.generated_at
    return InstalledModule(
        key=spec.key,
        module_name=spec.module_name,
        display_name=spec.display_name,
        version=spec.version,
        directory=directory,
        generated_at=generated_at,
        entity=spec.entity.display_name,
        field_count=len(spec.entity.fields),
        rule_count=len(spec.rules),
        base_path=spec.url_prefix,
    )
