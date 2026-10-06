# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Upgrading an installed module in place, without removing it first.

Adding a field, a link or a function to a register people already use used to
mean removing the module and building it again under the same key. An upgrade
does it in one step: the new spec is compared with the installed one and with
its table, and only what adds is accepted.

Accepted, whatever the register holds: a new field that may be empty, a new
link (empty on every saved record), a function switched on (status starts at
the first state on every saved record), a new state, a new rule, an added
choice, and any change of wording: names, labels, help text, units, rule
messages, whether a field shows in the list.

Refused while the register holds records, with :data:`UPGRADE_NOT_ADDITIVE`
and every problem listed: a field, a function, a state, a choice or a rule
taken away, a field holding another kind of value or a link pointing at
another kind of record, a new required field, a field becoming required while
records leave it empty, a rule checking something else, and the module's
project scoping turned on or off. A register with no records has nothing to
lose, so for it only a renamed record type is refused: that is another table,
and the old one would be left behind.

The order is chosen so that nothing is ever half applied:

1. Under a lock per key, in process and in PostgreSQL, so two upgrades of one
   module run one after the other and the second compares against the first.
2. In one database transaction: the table is planned against the spec, the new
   files are written to a staging folder, and the table is changed. A refusal
   or a failure here rolls the table back and removes the staging folder.
3. After the commit, the old folder is moved aside and the staged one renamed
   into place, and the module is loaded again. If the new code does not load,
   the old folder is put back and loaded. The columns the upgrade added stay:
   they may be empty, and the old code neither reads nor needs them. A table
   that was empty and created again is dropped again while still empty, so
   the old code creates its own.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.module_runtime_root import runtime_modules_dir
from app.modules.module_builder import generator, layout, links, refresh
from app.modules.module_builder.spec import STATUS_COLUMN, FieldSpec, ModuleSpec

logger = logging.getLogger(__name__)

# Refusal codes, for the frontend to say in the reader's language.
UPGRADE_NOT_ADDITIVE = "upgrade_not_additive"
NOT_INSTALLED = "not_installed"
MODULE_QUARANTINED = "module_quarantined"
MODULE_UNREADABLE = "module_unreadable"
LINKS_SWITCHED_OFF = "links_switched_off"
UPGRADE_FAILED = "upgrade_failed"

# What a layout problem is called in an upgrade refusal.
_LAYOUT_CODES = {
    layout.REMOVED: "field_removed",
    layout.CHANGED: "field_retyped",
    layout.NEW_REQUIRED: "field_new_required",
    layout.NOW_REQUIRED: "field_now_required",
    layout.NOW_OPTIONAL: "field_now_optional",
}

# Refused even when the register is empty.
_ALWAYS_REFUSED = {"entity_renamed"}

_locks: dict[str, asyncio.Lock] = {}


class UpgradeRefused(Exception):
    """The upgrade did not happen, or was undone. Nothing is half applied."""

    def __init__(self, status: int, code: str, message: str, params: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.params = params or {}


@dataclass(frozen=True)
class Change:
    """One thing the upgrade adds or rewords."""

    kind: str
    field: str | None = None
    feature: str | None = None
    state: str | None = None
    rule: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class Problem:
    """One thing the upgrade would take away or make unreadable."""

    code: str
    field: str | None = None
    label: str | None = None
    feature: str | None = None
    state: str | None = None
    rule: str | None = None
    empty: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class Outcome:
    changes: list[Change]
    records: int


# ── comparing two specs ─────────────────────────────────────────────────────


def compare(old: ModuleSpec, new: ModuleSpec) -> tuple[list[Change], list[Problem]]:
    """What going from *old* to *new* adds, and what it would take away."""
    changes: list[Change] = []
    problems: list[Problem] = []
    if old.entity.name != new.entity.name:
        problems.append(Problem("entity_renamed"))
        return changes, problems
    if old.entity.project_scoped != new.entity.project_scoped:
        problems.append(Problem("scope_changed"))

    before = {f.name: f for f in old.entity.fields}
    after = {f.name: f for f in new.entity.fields}
    for name, f in before.items():
        if name not in after:
            problems.append(Problem("field_removed", field=name, label=f.label))
    for name, f in after.items():
        was = before.get(name)
        if was is None:
            changes.append(Change("link_added" if f.type == "link" else "field_added", field=name))
            continue
        problems += _field_problems(was, f)
        if was != f and not (was.type != f.type or was.target != f.target):
            changes.append(Change("field_changed", field=name))

    _compare_rules(old, new, changes, problems)
    _compare_features(old, new, changes, problems)

    wording = ("display_name", "description", "icon", "author", "version", "category")
    if any(getattr(old, a) != getattr(new, a) for a in wording) or (
        old.entity.display_name != new.entity.display_name or old.entity.plural_name != new.entity.plural_name
    ):
        changes.append(Change("label_changed"))
    # A rule's message and the module's name both count as wording: said once.
    return list(dict.fromkeys(changes)), problems


def _field_problems(was: FieldSpec, now: FieldSpec) -> list[Problem]:
    if was.type != now.type or was.target != now.target:
        return [Problem("field_retyped", field=now.name, label=now.label)]
    gone = [o for o in was.options if o not in now.options]
    if now.type == "select" and gone:
        return [Problem("options_removed", field=now.name, label=now.label)]
    return []


def _compare_rules(old: ModuleSpec, new: ModuleSpec, changes: list[Change], problems: list[Problem]) -> None:
    before = {r.code: r for r in old.rules}
    after = {r.code: r for r in new.rules}
    for code in before:
        if code not in after:
            problems.append(Problem("rule_removed", rule=code))
    worded = False
    for code, rule in after.items():
        was = before.get(code)
        if was is None:
            changes.append(Change("rule_added", rule=code))
        elif was.model_copy(update={"message": rule.message}) != rule:
            problems.append(Problem("rule_changed", rule=code))
        elif was.message != rule.message:
            worded = True
    if worded:
        changes.append(Change("label_changed"))


def _compare_features(old: ModuleSpec, new: ModuleSpec, changes: list[Change], problems: list[Problem]) -> None:
    was, now = old.features, new.features
    for name in ("status", "due", "export", "comments"):
        before, after = getattr(was, name), getattr(now, name)
        on_before, on_after = bool(before), bool(after)
        if on_before and not on_after:
            problems.append(Problem("feature_removed", feature=name))
        elif on_after and not on_before:
            changes.append(Change("feature_added", feature=name))
        elif on_before and before != after:
            if name == "status":
                codes_before = [s.code for s in before.states]
                codes_after = [s.code for s in after.states]
                problems += [Problem("state_removed", state=c) for c in codes_before if c not in codes_after]
                changes += [Change("state_added", state=c) for c in codes_after if c not in codes_before]
                kept_before = [s for s in before.states if s.code in codes_after]
                kept_after = [s for s in after.states if s.code in codes_before]
                if kept_before != kept_after:
                    changes.append(Change("feature_changed", feature=name))
            else:
                changes.append(Change("feature_changed", feature=name))


def _layout_problems(plan: layout.Plan) -> list[Problem]:
    found = []
    for p in plan.problems:
        if p.kind == layout.REMOVED and p.column == STATUS_COLUMN:
            continue  # the status function switched off, which compare() names as such
        empty = p.empty if p.kind == layout.NOW_REQUIRED else None
        found.append(Problem(_LAYOUT_CODES[p.kind], field=p.column, label=p.label, empty=empty))
    return found


def _merged(problems: list[Problem]) -> list[Problem]:
    """One problem per field and code, the table's own count kept."""
    seen: dict[tuple[str, str | None, str | None, str | None, str | None], Problem] = {}
    for p in problems:
        key = (p.code, p.field, p.feature, p.state, p.rule)
        if key not in seen or (p.empty is not None and seen[key].empty is None):
            seen[key] = p
    return list(seen.values())


def refusal(records: int, problems: list[Problem]) -> UpgradeRefused:
    count = f"{records} record" if records == 1 else f"{records} records"
    return UpgradeRefused(
        409,
        UPGRADE_NOT_ADDITIVE,
        f"This upgrade would take away or change what the register's {count} hold "
        f"({', '.join(sorted({p.code for p in problems}))}). Nothing was changed. An upgrade can add fields, "
        "links, states, rules and functions, and change wording; anything else needs a new module.",
        {"records": records, "problems": [p.as_dict() for p in problems]},
    )


# ── the installed module ────────────────────────────────────────────────────


def installed_spec(key: str) -> ModuleSpec:
    """The spec the installed module was built from.

    Raises:
        UpgradeRefused: Nothing is installed under *key*, it is quarantined, or
            its spec cannot be read.
    """
    root = runtime_modules_dir()
    target = root / key
    if not (target / "spec.json").is_file():
        if (refresh.quarantine_dir(root) / key).is_dir():
            raise UpgradeRefused(
                409,
                MODULE_QUARANTINED,
                f"The module {key!r} is switched off for safety. Build it again from the builder instead.",
            )
        raise UpgradeRefused(404, NOT_INSTALLED, f"No module called {key!r} is installed.")
    try:
        payload = json.loads((target / "spec.json").read_text(encoding="utf-8"))
        payload.pop("generator", None)
        payload.pop("generated_at", None)
        return ModuleSpec.model_validate(payload)
    except (OSError, ValueError, AttributeError, ValidationError) as exc:
        raise UpgradeRefused(
            409, MODULE_UNREADABLE, f"The installed description of {key!r} cannot be read, so it cannot be upgraded."
        ) from exc


def _check(key: str, spec: ModuleSpec) -> ModuleSpec:
    old = installed_spec(key)
    switched_off = sorted({f.target for f in spec.link_fields if not links.available(f.target)})
    if switched_off:
        raise UpgradeRefused(
            409,
            LINKS_SWITCHED_OFF,
            f"The module links to {', '.join(switched_off)}, which is switched off on this server. "
            "Switch it on first, or remove the link.",
            {"targets": switched_off},
        )
    return old


def _verdict(old: ModuleSpec, spec: ModuleSpec, plan: layout.Plan) -> tuple[list[Change], list[Problem]]:
    changes, problems = compare(old, spec)
    problems = _merged(problems + _layout_problems(plan))
    if plan.records == 0:
        problems = [p for p in problems if p.code in _ALWAYS_REFUSED]
    return changes, problems


async def preview(key: str, spec: ModuleSpec) -> Outcome:
    """What upgrading *key* to *spec* would change. Writes nothing.

    Raises:
        UpgradeRefused: As :func:`upgrade` would, so the person learns before
            reading the files.
    """
    from app.database import engine

    old = _check(key, spec)
    async with engine.connect() as connection:
        plan = await connection.run_sync(layout.plan, spec)
        await connection.rollback()
    changes, problems = _verdict(old, spec, plan)
    if problems:
        raise refusal(plan.records, problems)
    return Outcome(changes, plan.records)


async def upgrade(key: str, spec: ModuleSpec, app: Any) -> Outcome:
    """Upgrade the installed module *key* to *spec*, all or nothing.

    Raises:
        UpgradeRefused: See the module docstring. On ``upgrade_failed`` the
            old code is serving again.
    """
    from app.database import engine

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock, _held_across_processes(key):
        old = _check(key, spec)
        if old == spec:
            async with engine.connect() as connection:
                plan = await connection.run_sync(layout.plan, spec)
                await connection.rollback()
            return Outcome([], plan.records)

        work = runtime_modules_dir() / refresh.WORK_DIR / "upgrade" / uuid.uuid4().hex
        try:
            async with engine.begin() as connection:
                plan = await connection.run_sync(layout.plan, spec)
                changes, problems = _verdict(old, spec, plan)
                if problems:
                    raise refusal(plan.records, problems)
                # Staged inside the transaction: a spec that cannot be written
                # rolls the table back with it.
                generator.write(spec, work)
                await connection.run_sync(layout.apply, spec, plan)
            await _swap_and_load(key, old, spec, work / key, app, recreated=plan.recreate)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        logger.info("module_builder: upgraded %s: %s", key, [c.as_dict() for c in changes])
        return Outcome(changes, plan.records)


@asynccontextmanager
async def _held_across_processes(key: str) -> AsyncIterator[None]:
    """A PostgreSQL session lock per key, for servers running several workers."""
    from sqlalchemy import text

    from app.database import engine

    if engine.dialect.name != "postgresql":
        yield
        return
    name = f"module_builder.upgrade:{key}"
    async with engine.connect() as connection:
        await connection.execute(text("SELECT pg_advisory_lock(hashtext(:name))"), {"name": name})
        await connection.commit()
        try:
            yield
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": name})
            await connection.commit()


async def _swap_and_load(
    key: str, old: ModuleSpec, spec: ModuleSpec, staged: Path, app: Any, *, recreated: bool
) -> None:
    from app.modules.module_builder import service

    root = runtime_modules_dir()
    target = root / key
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = root / refresh.WORK_DIR / "backups" / f"{key}-upgrade-{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)

    await _unload(key, spec.module_name, app)
    os.replace(target, backup)
    try:
        os.replace(staged, target)
    except OSError as exc:
        os.replace(backup, target)
        await _load_back(key, old, app)
        raise UpgradeRefused(409, UPGRADE_FAILED, f"The new code could not be put in place: {exc}") from exc

    try:
        await service._load_into(app, spec)
    except Exception as exc:
        logger.exception("module_builder: %s did not load after the upgrade; putting the old code back", key)
        await _unload(key, spec.module_name, app)
        if recreated:
            await _empty_again(spec)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(backup, target)
        await _load_back(key, old, app)
        raise UpgradeRefused(
            409, UPGRADE_FAILED, f"The upgraded module did not load, so the previous version is back. {exc}"
        ) from exc


async def _unload(key: str, module_name: str, app: Any) -> None:
    from app.core.module_loader import module_loader
    from app.core.permissions import permission_registry
    from app.modules.module_builder import service

    try:
        await module_loader.disable_module(module_name, app)
    except Exception:
        logger.warning("module_builder: %s did not unload cleanly", module_name, exc_info=True)
    service._forget(key)
    module_loader.forget_module(module_name)
    permission_registry.unregister_module_permissions(key)


async def _load_back(key: str, old: ModuleSpec, app: Any) -> None:
    from app.modules.module_builder import service

    try:
        await service._load_into(app, old)
    except Exception:
        logger.critical("module_builder: %s could not be loaded again after a failed upgrade", key, exc_info=True)


async def _empty_again(spec: ModuleSpec) -> None:
    """Drop a table the upgrade created again, while it is still empty."""
    from sqlalchemy import inspect, text

    from app.database import engine

    try:
        async with engine.begin() as connection:
            if not await connection.run_sync(lambda sync: inspect(sync).has_table(spec.table_name)):
                return  # the new code never got as far as creating it
            table = connection.dialect.identifier_preparer.quote(spec.table_name)
            count = (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            if count == 0:
                await connection.execute(text(f"DROP TABLE {table}"))
    except Exception:
        logger.warning("module_builder: %s could not be emptied again for the old code", spec.key, exc_info=True)
