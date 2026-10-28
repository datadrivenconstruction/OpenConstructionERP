# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permits module wiring: router guards, approval kind, messages, model/migration parity, rule set."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import typing
from datetime import date
from pathlib import Path

import pytest

from app.modules.permits import router as permits_router
from app.modules.permits.messages import is_key_present

MODULE_DIR = Path(permits_router.__file__).parent
MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v73_permits.py"


def test_every_project_handler_verifies_access() -> None:
    """Rule 24: every project-scoped handler takes its service from ``_permits_service``, which checks access.

    The same is pinned handler by handler in ``tests/unit/test_idor_router_guards.py``.
    """
    for route in permits_router.router.routes:
        if "{project_id}" not in route.path:
            continue
        assert "await _permits_service(project_id, user_id, session)" in inspect.getsource(route.endpoint), route.path
    assert "await verify_project_access(project_id, user_id, session)" in inspect.getsource(
        permits_router._permits_service
    )
    for route in permits_router.router.routes:
        # No project handler builds the service on its own.
        assert "{project_id}" not in route.path or "PermitService(" not in inspect.getsource(route.endpoint)


def test_decisions_need_manage_and_discharge_needs_verify() -> None:
    perms = {}
    for route in permits_router.router.routes:
        deps = [d.dependency for d in route.dependencies]
        perms[(route.path, tuple(route.methods))] = {getattr(d, "permission", None) for d in deps}
    decision = next(v for (p, _m), v in perms.items() if p.endswith("/decision"))
    assert decision == {"permits.manage"}
    discharge = next(v for (p, _m), v in perms.items() if p.endswith("/discharge"))
    assert discharge == {"permits.verify"}
    # Reading the notice with the AI writes proposals: it is an editor's action and takes no body.
    extract = next(r for r in permits_router.router.routes if r.path.endswith("/condition-proposals/extract"))
    assert {getattr(d.dependency, "permission", None) for d in extract.dependencies} == {"permits.edit"}
    assert set(inspect.signature(extract.endpoint).parameters) == {"project_id", "permit_id", "session", "user_id"}


def test_a_get_route_never_writes_the_roadmap() -> None:
    """Round 2, C1: the binding state is derived on read; only a structural write stores it."""
    from app.modules.permits.service import PermitService

    for name in ("get_roadmap", "roadmap_view", "require_roadmap"):
        src = inspect.getsource(getattr(PermitService, name))
        assert "_mirror_binding" not in src and "flush(" not in src, name
    callers = [
        name
        for name, fn in vars(PermitService).items()
        if callable(fn) and "_mirror_binding(" in inspect.getsource(fn) and name != "_mirror_binding"
    ]
    assert callers == ["_structural_guard"]


async def test_the_module_subscribes_again_after_the_bus_was_emptied(monkeypatch) -> None:
    """A flag beside the bus outlives the handlers; ``subscribe_once`` does not."""
    from app.core.events import event_bus
    from app.modules.permits import events

    seen: list[tuple[str, str]] = []

    async def record(data: dict, *, verdict: str, session_factory=None) -> None:
        seen.append((verdict, data["target_id"]))

    monkeypatch.setattr(events, "handle_route_event", record)
    kept = {name: list(handlers) for name, handlers in event_bus._handlers.items()}
    wildcard = list(event_bus._wildcard_handlers)
    try:
        events.register_permit_subscribers()
        event_bus.clear()
        await event_bus.publish("approval_routes.instance.rejected", {"target_id": "lost"})
        assert seen == []
        events.register_permit_subscribers()
        events.register_permit_subscribers()
        await event_bus.publish("approval_routes.instance.rejected", {"target_id": "a"})
        await event_bus.publish("approval_routes.instance.cancelled", {"target_id": "b"})
        # Heard again, and once each: registering twice does not double the handler.
        assert seen == [("rejected", "a"), ("cancelled", "b")]
    finally:
        event_bus.clear()
        for name, handlers in kept.items():
            event_bus._handlers[name].extend(handlers)
        event_bus._wildcard_handlers.extend(wildcard)


def test_every_record_read_is_served_with_what_the_caller_may_do() -> None:
    """A button follows the server: each read of a record a user acts on builds its ``can`` from the caller."""
    reads = {
        "/projects/{project_id}/roadmap",
        "/projects/{project_id}/requirements",
        "/projects/{project_id}/applications",
        "/projects/{project_id}/applications/{application_id}",
        "/projects/{project_id}/permits",
        "/projects/{project_id}/conditions",
        "/projects/{project_id}/conditions/{condition_id}",
    }
    seen = set()
    for route in permits_router.router.routes:
        if "GET" in route.methods and route.path.removeprefix(permits_router.router.prefix) in reads:
            assert "_caller(payload, user_id)" in inspect.getsource(route.endpoint), route.path
            seen.add(route.path.removeprefix(permits_router.router.prefix))
    assert seen == reads
    # Nothing but the guards decides a flag: the service builds every one through ``guards``.
    from app.modules.permits.service import PermitService

    for name in ("roadmap_can", "requirement_can", "application_can", "decision_can", "permit_can", "condition_can"):
        assert "guards.flag(" in inspect.getsource(getattr(PermitService, name)), name


def test_approval_target_kind_registered_in_model_and_schema() -> None:
    from app.modules.approval_routes.models import TARGET_KINDS
    from app.modules.approval_routes.schemas import TargetKindLiteral

    assert "permit_application" in TARGET_KINDS
    assert "permit_application" in typing.get_args(TargetKindLiteral)


def test_every_error_code_has_an_english_and_german_message() -> None:
    codes: set[str] = set()
    for path in MODULE_DIR.glob("*.py"):
        codes |= set(
            re.findall(
                r'(?:PermitError|not_found|conflict|forbidden|not_applicable|refused|ClockError)\(\s*"([a-z_]+)"',
                path.read_text("utf-8"),
            )
        )
    assert len(codes) > 50
    for code in codes:
        for loc in ("en", "de"):
            assert is_key_present(f"permits.errors.{code}", loc), (code, loc)


def test_every_rule_has_messages() -> None:
    from app.modules.permits.validators import PERMIT_RULES

    for rule in PERMIT_RULES:
        for loc in ("en", "de"):
            assert is_key_present(f"permits.rules.{rule.key}.fail", loc), rule.key
            assert is_key_present(f"permits.rules.{rule.key}.suggestion", loc), rule.key


def _load_migration():
    spec = importlib.util.spec_from_file_location("v73_permits", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hook_name(table_name: str, columns: list[str]) -> set[str]:
    """The names ``app.core.pg_optimizations`` gives an index it attaches on exactly these columns."""
    from app.core.pg_optimizations import _index_name

    return {_index_name(table_name, columns), _index_name(table_name, columns, gin=True)}


def _permits_tables() -> dict[str, typing.Any]:
    from app.database import Base
    from app.modules.permits import models  # noqa: F401

    return {n: t for n, t in Base.metadata.tables.items() if n.startswith("oe_permits_")}


def test_migration_matches_models() -> None:
    """Columns, constraint names and indexes with their columns are the same in model and migration.

    ``app.core.pg_optimizations`` attaches its own indexes to the shared metadata after any
    ``create_all`` in the same process, and no revision creates those. An index the models carry
    and the revision does not is accepted only under exactly the name the hook gives its columns,
    so the comparison holds whatever ran before it; anything else is a real difference.
    """
    mod = _load_migration()
    assert mod.revision == "v73_permits"
    # Where the revision sits in the chain is decided when the branches are joined; it must name
    # a revision that exists.
    assert (MIGRATION.parent / f"{mod.down_revision}.py").exists(), mod.down_revision
    tables = _permits_tables()
    assert {t for t, _c, _i in mod._TABLES} == set(tables)
    for name, columns, indexes in mod._TABLES:
        table = tables[name]
        cols = columns()
        constraints = set()
        col_names = {"id", "created_at", "updated_at"}
        for c in cols:
            if hasattr(c, "foreign_keys"):
                col_names.add(c.name)
                constraints |= {fk.name for fk in c.foreign_keys}
            elif getattr(c, "name", None):
                constraints.add(c.name)
        assert col_names == {c.name for c in table.columns}, name
        model_constraints = {c.name for c in table.constraints if c.name and not c.name.startswith("pk_")}
        model_constraints |= {fk.name for c in table.columns for fk in c.foreign_keys if fk.name}
        assert constraints == model_constraints, name
        declared = {n: list(c) for n, c in indexes}
        model_idx = {i.name: [c.name for c in i.columns] for i in table.indexes}
        assert all(model_idx.get(n) == c for n, c in declared.items()), (name, declared, model_idx)
        beside = {n: c for n, c in model_idx.items() if n not in declared}
        # Only the offenders go into the message: the whole dict is long once the hook has run, and the
        # assertion rewriter elides the middle of a long repr, which can hide the very index at fault.
        foreign = {n: c for n, c in beside.items() if n not in _hook_name(name, c)}
        assert not foreign, (name, foreign)


def test_the_comparison_holds_after_the_platform_attached_its_indexes() -> None:
    """Run alone or after a ``create_all`` elsewhere in the process, the answer is the same."""
    from sqlalchemy import Index

    table = _permits_tables()["oe_permits_roadmap"]
    # Every index the revision declares under the name the hook would give it, absent from the models
    # until the hook has run in this process: the comparison must hold with or without them.
    declared = next(indexes for n, _c, indexes in _load_migration()._TABLES if n == table.name)
    late = [
        Index(n, *[table.c[c] for c in cols])
        for n, cols in ((n, list(c)) for n, c in declared)
        if n in _hook_name(table.name, cols) and n not in {i.name for i in table.indexes}
    ]
    stray = Index("ix_oe_permits_roadmap_stray", table.c["jurisdiction"])
    try:
        with pytest.raises(AssertionError, match="stray"):
            test_migration_matches_models()
        table.indexes.discard(stray)
        test_migration_matches_models()
    finally:
        for ix in [*late, stray]:
            table.indexes.discard(ix)


def test_no_index_repeats_one_the_platform_attaches_under_another_name() -> None:
    """The hook adds (project_id, status) and (project_id, created_at) under its own name.

    A module index on the same columns under another name would be built twice on every
    install, so those carry the hook's name in the models and in the revision.
    """
    for name, table in _permits_tables().items():
        for ix in table.indexes:
            cols = [c.name for c in ix.columns]
            if cols in (["project_id", "status"], ["project_id", "created_at"]):
                assert ix.name in _hook_name(name, cols), (name, ix.name)


def test_migration_is_inspector_guarded() -> None:
    tree = ast.parse(MIGRATION.read_text("utf-8"))
    src = ast.unparse(tree)
    assert "get_table_names()" in src and "get_indexes(table)" in src


@pytest.mark.asyncio
async def test_rule_set_runs_on_a_payload() -> None:
    from app.core.validation.engine import ValidationContext
    from app.modules.permits.validators import PERMIT_RULES

    payload = {
        "today": date(2026, 10, 11).isoformat(),
        "catalogue": None,
        "requirements": [{"id": "r1", "permit_type_code": "x", "applicable": True, "applicant_role": "owner"}],
        "edges": [{"requirement": "a", "depends_on": "b", "on": "granted"}, {"requirement": "b", "depends_on": "a"}],
        "timeline": [],
        "applications": [],
        "decisions": [],
        "permits": [],
        "conditions": [
            {
                "id": "c1",
                "number": "1",
                "permit_id": "p",
                "confirmed": True,
                "state": "open",
                "kind": "suspensive",
                "trigger": "before_start",
                "owner_user_id": None,
                "overdue": False,
            },
        ],
        "discharges": [],
    }
    ctx = ValidationContext(data=payload, metadata={"locale": "de"})
    failed = set()
    for rule in PERMIT_RULES:
        for r in await rule().validate(ctx):
            if not r.passed:
                failed.add(r.rule_id)
                assert r.message and "permits.rules" not in r.message
    assert {
        "permits.requirement_has_applicant_and_owner",
        "permits.dependency_acyclic",
        "permits.condition_has_trigger_and_owner",
        "permits.suspensive_condition_blocks_start",
    } <= failed


def test_no_write_route_takes_a_date_from_the_client() -> None:
    """Review finding 5: only reads may be asked "as of"; a write happens on the server's date."""
    for route in permits_router.router.routes:
        if route.methods <= {"GET", "HEAD"}:
            continue
        assert "today" not in inspect.signature(route.endpoint).parameters, route.path


def test_the_service_is_told_what_the_caller_may_do_never_a_role() -> None:
    """Lead decision: permission checks live in the router and reach the service as booleans."""
    from app.modules.permits import service

    assert not re.search(r"\bactor_role\b|\brole: str", inspect.getsource(service.PermitService))
    assert not re.search(r"[\"'](admin|manager|editor|viewer)[\"']", inspect.getsource(service))
    assert "permission_registry.role_has_permission" in inspect.getsource(permits_router._can)


def test_the_sweep_is_a_registered_periodic_process() -> None:
    """Review finding 10, rule 17: escalation does not depend on somebody pressing a button."""
    from app.core.processes import builtin

    src = inspect.getsource(builtin.register_builtin_processes)
    assert '"permits_sweep"' in src and "permits_tick" in src
    assert "run_sweep_once" in inspect.getsource(builtin.permits_tick)


def test_the_register_export_declares_the_language_it_was_written_in() -> None:
    """The bundle answers a missing locale in English, so that is what the header must say."""
    import inspect

    from app.modules.permits import export, router

    for asked, written in (("en", "en"), ("de", "de"), ("fr", "fr"), ("", "en"), (None, "en"), ("zz", "en")):
        assert export.written_locale(asked) == written, asked
    source = inspect.getsource(router.export)
    assert "Content-Language" in source and "written_locale" in source
    # The sheet is rendered in that same language, not in the one asked for.
    assert "get_locale() or" not in source
