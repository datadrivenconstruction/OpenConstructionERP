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
import os
import re
import shutil
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.module_runtime_root import attach_runtime_root, runtime_modules_dir
from app.core.permissions import permission_registry
from app.modules.module_builder import generator, layout, links, refresh
from app.modules.module_builder.schemas import Suggestion, SuggestionPatch
from app.modules.module_builder.spec import (
    SCHEMA_VERSION,
    DueFeature,
    FieldSpec,
    ModuleSpec,
    StatusFeature,
    url_prefix_for,
)

logger = logging.getLogger(__name__)

MAX_DESCRIPTION = 4000

SYSTEM_PROMPT = """\
You describe one module for a construction cost management platform.

You never write code. You return a single JSON object with two parts: the
module itself, and suggestions for what it could also do. A deterministic
generator turns the module into code. The suggestions are shown to a person,
who decides which to add, so never put one into the module: no link fields and
no functions there. If the description cannot be expressed in the schema below,
return the closest thing that can be, rather than inventing fields the schema
does not have.

Return JSON only. No prose, no markdown fence.

{
  "module": {
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
          "name": "snake_case, never id, project_id, created_at, updated_at, metadata or status",
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
  },
  "suggestions": [
    {
      "kind": "link | feature",
      "target": "only for a link: contract | contact | schedule_activity | document | user",
      "feature": "only for a feature: status | due | export | comments",
      "field_label": "only for a link: what a person reads on the new field",
      "due_field": "only for due: the name of a date or datetime field of the module",
      "states": [{"code": "snake_case", "label": "what a person reads", "done": false}],
      "confidence": "high | medium | low",
      "reason": "one short sentence for the person deciding"
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

Suggestions. A link points each record at a record another part of the
platform keeps:
- contract: a contract of the same project
- contact: a company or person in the address book, such as a supplier
- schedule_activity: an activity in the project schedule
- document: a document in the project's document register
- user: a person who uses the platform, such as whoever is responsible
A feature is a function the module can have:
- status: records move through two to eight states; give "states", the first
  is where a record starts, and mark finished ones "done": true
- due: one date field is a deadline, reminded before it passes; give "due_field"
- export: the list can be downloaded as CSV or Excel
- comments: people discuss each record in a comment thread
Suggest only what this register would use, at most one per target or feature.
Confidence is high when the description asks for it, medium when a register
like this usually needs it, and low when it might help.
"""

# Appended to SYSTEM_PROMPT when the wizard says which language it reads in.
LANGUAGE_INSTRUCTION = (
    "\nWrite every display name, description, label, plural name, select option, rule message, "
    "state label and reason in {language}. Keys, names, codes and the JSON itself stay as described."
)

# The languages the wizard ships, by the name the assistant is told.
LANGUAGE_NAMES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "tr": "Turkish",
    "zh": "Chinese",
    "ja": "Japanese",
}

# The assistant's reason is shown as written; past this it is cut.
MAX_REASON = 200


class DraftRefused(Exception):
    """The assistant answered, but not with a module this platform can build."""

    def __init__(self, reason: str, raw: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw = raw


class InstallRefused(Exception):
    """Installation stopped before anything was changed, or was undone.

    ``code`` and ``params`` are set when the frontend should say why in the
    reader's language rather than show the English message, which is then the
    fallback. Only :data:`layout.LAYOUT_CONFLICT` uses them so far.
    """

    def __init__(self, message: str, *, code: str | None = None, params: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.params = params or {}


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
    # "quarantined" for a module the server refused to load at startup, with
    # the reason in ``problem`` as ``{"code", "params"}``. Its routes are not
    # mounted, so ``base_path`` answers 404 until it is built again.
    status: str = "installed"
    problem: dict[str, Any] | None = None


async def draft_spec(session: Any, user_id: str, description: str) -> ModuleSpec:
    """Ask the configured assistant to describe a module, and validate the answer.

    The spec half of :func:`draft`, for callers that do not show suggestions.
    """
    spec, _suggestions = await draft(session, user_id, description)
    return spec


async def draft(
    session: Any, user_id: str, description: str, locale: str | None = None
) -> tuple[ModuleSpec, list[Suggestion]]:
    """Ask the configured assistant to describe a module, and validate the answer.

    Args:
        session: Database session, used to read the user's AI settings.
        user_id: The user asking, whose provider and key are used.
        description: What they want, in their own words.
        locale: The language the wizard reads in; labels and reasons come back in it.

    Returns:
        A validated spec with no links and no features, and the assistant's
        suggestions for those. Nothing has been written anywhere, and nothing
        suggested is in the spec: a person ticks what they want.

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
        system_prompt(locale),
        description,
        max_tokens=4096,
        model=model,
    )
    logger.info("module_builder: drafted a spec with %s, %s tokens", provider, tokens)

    payload = extract_json(text)
    if not isinstance(payload, dict):
        raise DraftRefused("The assistant did not return a module description.", raw=text[:2000])
    spec, suggestions = draft_from_payload(payload, locale)
    # Recorded here rather than in spec_from_payload, which also validates
    # payloads that no model produced, and rather than in the router, so that
    # the claim is made by the code that actually called the model. The model
    # does not get to say this about itself: whatever it puts in the field is
    # replaced.
    return spec.model_copy(update={"drafted_by": "assistant"}), suggestions


def system_prompt(locale: str | None = None) -> str:
    """The instructions, with the reader's language when the wizard gave one."""
    if not locale:
        return SYSTEM_PROMPT
    base = locale.split("-")[0].lower()
    language = LANGUAGE_NAMES.get(base)
    if language is None:
        # Only a tag the request model already checked reaches here, so it is
        # safe to name as it is.
        language = f"the language with the tag {locale}"
    return SYSTEM_PROMPT + LANGUAGE_INSTRUCTION.format(language=language)


def draft_from_payload(payload: dict[str, Any], locale: str | None = None) -> tuple[ModuleSpec, list[Suggestion]]:
    """Split an assistant's answer into the base spec and its suggestions.

    Accepts the two-part answer the prompt asks for and the bare module an
    older prompt returned. Whatever the assistant put into the module that
    belongs in a suggestion - a link field, a function - is taken out: nothing
    it proposes reaches the spec unless a person ticks it.
    """
    module = payload.get("module") if isinstance(payload.get("module"), dict) else payload
    module = dict(module)
    module.pop("features", None)
    module.pop("schema_version", None)
    entity = module.get("entity")
    if isinstance(entity, dict) and isinstance(entity.get("fields"), list):
        links_out = [f for f in entity["fields"] if isinstance(f, dict) and f.get("type") == "link"]
        removed = {f.get("name") for f in links_out}
        kept = [
            {k: v for k, v in f.items() if k != "target"} if isinstance(f, dict) else f
            for f in entity["fields"]
            if not (isinstance(f, dict) and f.get("type") == "link")
        ]
        module["entity"] = {**entity, "fields": kept}
        if removed and isinstance(module.get("rules"), list):
            module["rules"] = [
                r
                for r in module["rules"]
                if not (isinstance(r, dict) and (r.get("field") in removed or r.get("other_field") in removed))
            ]
    else:
        links_out = []
    module["schema_version"] = SCHEMA_VERSION
    spec = spec_from_payload(module)
    raw = list(payload.get("suggestions")) if isinstance(payload.get("suggestions"), list) else []
    # A link the assistant wrote into the module anyway is still its idea:
    # offered as a suggestion, after the ones it made as asked.
    raw += [
        {"kind": "link", "target": f.get("target"), "field_label": f.get("label"), "confidence": "medium"}
        for f in links_out
    ]
    return spec, suggestions_from_assistant(spec, raw, locale)


def suggestions_from_assistant(spec: ModuleSpec, raw: list[Any], locale: str | None = None) -> list[Suggestion]:
    """The assistant's suggestions, rebuilt by the server from the spec.

    The assistant chooses what to suggest, how sure it is and why. The patch
    each one carries is built here, from the validated spec and the same
    defaults the rule-based suggestions use, so a suggestion can only ever
    propose something the spec would accept. Anything that does not fit is
    dropped rather than repaired.
    """
    from app.modules.module_builder import suggest

    out: list[Suggestion] = []
    seen: set[str] = set()
    names = {f.name for f in spec.entity.fields}
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        try:
            suggestion = _assistant_suggestion(spec, item, names, locale, suggest)
        except (ValueError, ValidationError, KeyError, TypeError):
            suggestion = None
        if suggestion is not None and suggestion.id not in seen:
            seen.add(suggestion.id)
            out.append(suggestion)
    return out


def _assistant_suggestion(
    spec: ModuleSpec, item: dict[str, Any], names: set[str], locale: str | None, suggest: Any
) -> Suggestion | None:
    confidence = item.get("confidence") if item.get("confidence") in {"high", "medium", "low"} else "low"
    reason = _clean_reason(item.get("reason"))
    kind = item.get("kind")
    if kind == "link":
        target = item.get("target")
        if target not in links.LINK_TARGETS:
            return None
        name = links.LINK_TARGETS[target].field_name
        candidate, n = name, 2
        while candidate in names or candidate == "status":
            candidate, n = f"{name}_{n}", n + 1
        label = _clean_reason(item.get("field_label"), limit=80) or suggest.link_label(target, locale)
        field = FieldSpec(name=candidate, label=label, type="link", target=target)
        return Suggestion(
            id=f"link:{target}",
            kind="link",
            target=target,
            confidence=confidence,
            reason=reason,
            patch=SuggestionPatch(field=field),
        )
    if kind != "feature":
        return None
    feature = item.get("feature")
    scoped = spec.entity.project_scoped
    if feature == "status":
        if "status" in names:
            return None
        try:
            status = StatusFeature.model_validate({"states": item.get("states")})
        except ValidationError:
            status = suggest.default_status(locale)
        patch = SuggestionPatch(status=status)
    elif feature == "due":
        field = next((f for f in spec.entity.fields if f.name == item.get("due_field")), None)
        if field is None or field.type not in {"date", "datetime"} or not scoped:
            return None
        patch = SuggestionPatch(due=DueFeature(field=field.name, remind_days_before=suggest.DEFAULT_REMIND_DAYS))
    elif feature == "export":
        patch = SuggestionPatch(export=True)
    elif feature == "comments":
        if not scoped:
            return None
        patch = SuggestionPatch(comments=True)
    else:
        return None
    return Suggestion(
        id=f"feature:{feature}", kind="feature", feature=feature, confidence=confidence, reason=reason, patch=patch
    )


def _clean_reason(value: Any, limit: int = MAX_REASON) -> str | None:
    """One line of plain text, or nothing."""
    if not isinstance(value, str):
        return None
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


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
        InstallRefused: The key is taken, a table kept from an earlier install
            holds records this spec would lose (code ``layout_conflict``), or
            the module failed to load.
    """
    root = runtime_modules_dir()
    target = root / spec.key
    if target.exists():
        raise InstallRefused(
            f"A module called {spec.key!r} is already installed. Remove it first, or choose another name."
        )
    # Refused rather than followed: loading a module enables the modules it
    # depends on, so a link to a part of the platform switched off here would
    # switch it back on as a side effect of installing something else.
    switched_off = sorted({f.target for f in spec.link_fields if not links.available(f.target)})
    if switched_off:
        raise InstallRefused(
            f"The module links to {', '.join(switched_off)}, which is switched off on this server. "
            "Switch it on first, or remove the link."
        )
    # Before any file is written: a table an earlier install left behind
    # either takes this spec, or the install stops here with nothing changed.
    await _fit_existing_table(spec)

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

    _release_quarantine(spec.key)
    logger.info("module_builder: installed %s at %s", spec.module_name, target)
    return _from_spec(spec, target)


def _quarantined_dir(key: str) -> Path | None:
    place = refresh.quarantine_dir(runtime_modules_dir()) / key
    return place if place.is_dir() else None


def _release_quarantine(key: str) -> None:
    """A module built again under a quarantined key replaces the quarantined copy.

    The copy is kept with the other backups rather than deleted: it is what
    the server refused to run, and someone may want to read it.
    """
    place = _quarantined_dir(key)
    if place is None:
        return
    root = runtime_modules_dir()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = root / refresh.WORK_DIR / "backups" / f"{key}-quarantined-{stamp}"
    try:
        backup.parent.mkdir(parents=True, exist_ok=True)
        os.replace(place, backup)
    except OSError:
        logger.warning("module_builder: the quarantined copy of %s stays at %s", key, place, exc_info=True)


async def _fit_existing_table(spec: ModuleSpec) -> None:
    """Bring a table kept from an earlier install up to this spec, or refuse.

    See :mod:`app.modules.module_builder.layout` for what is added and what is
    refused. Planned and applied in one transaction, so a refusal changes
    nothing and a change is never half made. If the module then fails to load,
    the columns added here stay: they are empty, and the records are untouched.
    """
    from app.database import engine

    try:
        async with engine.begin() as connection:
            await connection.run_sync(layout.prepare, spec)
    except layout.LayoutConflict as exc:
        raise InstallRefused(str(exc), code=layout.LAYOUT_CONFLICT, params=exc.params) from exc


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
    if not _IDENTIFIER.match(key):
        # Joined onto paths below, so "..", "." or a separator never gets that far.
        raise InstallRefused(f"No module called {key!r} is installed in the runtime module folder.")
    root = runtime_modules_dir()
    target = root / key
    if not target.is_dir():
        quarantined = _quarantined_dir(key)
        if quarantined is None:
            raise InstallRefused(f"No module called {key!r} is installed in the runtime module folder.")
        return await _remove_quarantined(key, quarantined, drop_data=drop_data)

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


async def _remove_quarantined(key: str, directory: Path, *, drop_data: bool) -> dict[str, Any]:
    """Remove a module the server refused to load, without importing any of it.

    It was never loaded, so there are no routes, permissions or imports to take
    down. The table is dropped by the name its spec gives, never through its
    own code, which is what was not trusted to run.
    """
    dropped = await _drop_table_by_name(key, directory) if drop_data else False
    shutil.rmtree(directory, ignore_errors=True)
    logger.info("module_builder: removed quarantined %s, data dropped: %s", key, dropped)
    return {"key": key, "module_name": f"oe_{key}", "removed": True, "data_dropped": dropped}


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


async def _drop_table_by_name(key: str, directory: Path) -> bool:
    from sqlalchemy import text

    from app.database import engine

    try:
        payload = json.loads((directory / "spec.json").read_text(encoding="utf-8"))
        entity = payload["entity"]["name"]
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("module_builder: %s has no readable spec, leaving the data alone", key, exc_info=True)
        return False
    if payload.get("key") != key or not all(isinstance(n, str) and _IDENTIFIER.match(n) for n in (key, entity)):
        logger.warning("module_builder: %s names a table this module does not own, leaving the data alone", key)
        return False
    async with engine.begin() as connection:
        table = connection.dialect.identifier_preparer.quote(f"oe_{key}_{entity}")
        await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
    return True


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
    listed = [item for item in found if item is not None]
    keys = {item.key for item in listed}
    for directory, note in refresh.quarantined(root):
        item = _from_disk(directory)
        if item is None or item.key in keys:
            continue
        problem = {"code": note.get("code") or refresh.UNVERIFIABLE, "params": note.get("params") or {}}
        listed.append(replace(item, status="quarantined", problem=problem))
    return listed


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
