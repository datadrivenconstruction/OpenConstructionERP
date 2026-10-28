# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Static wiring of the stakeholders module: IDOR guards, migration parity, messages, approval kind.

The repository's IDOR census only covers the modules it lists, so a new module
passes it untouched; this file is the module's own guard (SPEC rule 22).
"""

from __future__ import annotations

import ast
import importlib.util
import re
import typing
from pathlib import Path

import pytest

_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "stakeholders"
_MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v76_stakeholders.py"


def _handlers() -> list[ast.AsyncFunctionDef]:
    tree = ast.parse((_MODULE / "router.py").read_text(encoding="utf-8"))
    return [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.decorator_list]


def _route_path(fn: ast.AsyncFunctionDef) -> str:
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant):
            return str(d.args[0].value)
    return ""


def test_every_project_route_calls_verify_project_access_first() -> None:
    project_routes = [fn for fn in _handlers() if "{project_id}" in _route_path(fn)]
    assert len(project_routes) >= 35
    missing = []
    for fn in project_routes:
        first_await = next(
            (n for n in ast.walk(fn) if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)),
            None,
        )
        name = getattr(getattr(first_await, "value", None), "func", None)
        if not (isinstance(name, ast.Name) and name.id == "verify_project_access"):
            missing.append(fn.name)
    assert missing == []


def test_module_imports_and_mounts() -> None:
    from app.modules.stakeholders import events, evidence, export, seed, service, validators  # noqa: F401
    from app.modules.stakeholders.manifest import manifest
    from app.modules.stakeholders.router import router

    assert manifest.name == "oe_stakeholders"
    paths = {r.path for r in router.routes}
    assert "/projects/{project_id}/organisation/who-decides" in paths
    assert "/projects/{project_id}/stakeholders/{stakeholder_id}/assessments" in paths


def test_every_route_has_a_permission_dependency() -> None:
    src = (_MODULE / "router.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if line.startswith("@router."):
            assert re.search(r"dependencies=\[(READ|EDIT|ORG|CATALOGUE)\]", line), line


def _load_migration():
    spec = importlib.util.spec_from_file_location("v76_stakeholders", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _index_differences(table: str, declared: dict[str, list[str]], carried: dict[str, list[str]]) -> list[str]:
    """What separates the indexes a revision declares from the ones a model table carries.

    ``app.core.pg_optimizations`` attaches its own indexes to the metadata after
    any ``create_all`` in the same process, and no revision in the repository
    creates those. An index the revision does not declare is therefore accepted
    only when its name is exactly the one the hook gives its columns. Anything
    else is a difference.
    """
    from app.core.pg_optimizations import _index_name

    out = [f"{n}: declared by the revision, missing on the model" for n in sorted(set(declared) - set(carried))]
    for name, cols in sorted(carried.items()):
        if name in declared:
            if declared[name] != cols:
                out.append(f"{name}: revision {declared[name]}, model {cols}")
        elif name != _index_name(table, cols):
            out.append(f"{name}: on the model, not in the revision")
    return out


def test_only_an_index_named_by_the_platform_hook_may_be_missing_from_the_revision() -> None:
    import sqlalchemy as sa

    from app.core.pg_optimizations import _index_name

    table = sa.Table(
        "oe_stakeholders_probe",
        sa.MetaData(),
        sa.Column("project_id", sa.String(36)),
        sa.Column("status", sa.String(20)),
        sa.Column("created_at", sa.DateTime()),
        sa.Index("ix_oe_stk_probe_own", "project_id", "status"),
    )
    declared = {"ix_oe_stk_probe_own": ["project_id", "status"]}

    def carried() -> dict[str, list[str]]:
        return {i.name: [c.name for c in i.columns] for i in table.indexes}

    assert _index_differences(table.name, declared, carried()) == []
    # What the hook leaves behind after a create_all somewhere earlier in the same process.
    sa.Index(_index_name(table.name, ["project_id"]), table.c.project_id)
    sa.Index(_index_name(table.name, ["project_id", "created_at"]), table.c.project_id, table.c.created_at)
    assert _index_differences(table.name, declared, carried()) == []
    # A hook name on other columns, a stray index, a changed column list and a dropped index are all differences.
    sa.Index(_index_name(table.name, ["project_id", "status"]), table.c.status)
    sa.Index("ix_oe_stk_probe_stray", table.c.status)
    found = _index_differences(table.name, {**declared, "ix_oe_stk_probe_gone": ["status"]}, carried())
    assert [line.split(":")[0] for line in found] == [
        "ix_oe_stk_probe_gone",
        "ix_oe_stakeholders_probe_project_id_status",
        "ix_oe_stk_probe_stray",
    ]
    assert _index_differences(table.name, {"ix_oe_stk_probe_own": ["status"]}, {"ix_oe_stk_probe_own": ["project_id"]})


def test_migration_matches_the_models() -> None:
    from app.database import Base
    from app.modules.stakeholders import models  # noqa: F401

    mig = _load_migration()
    assert mig.revision == "v76_stakeholders"
    # Where the revision sits in the chain is decided when the branches are joined; it must name a
    # revision that exists.
    assert (_MIGRATION.parent / f"{mig.down_revision}.py").exists(), mig.down_revision
    tables = {name: (cols, idx) for name, cols, idx in mig._TABLES}
    model_tables = {n: t for n, t in Base.metadata.tables.items() if n.startswith("oe_stakeholders_")}
    assert set(tables) == set(model_tables)
    for name, (cols, idx) in tables.items():
        mig_cols = {c.name for c in mig._base() + [c for c in cols() if hasattr(c, "name") and hasattr(c, "type")]}
        assert mig_cols == {c.name for c in model_tables[name].columns}, name
        declared = {index_name: index_cols for index_name, index_cols, _kw in idx}
        carried = {i.name: [c.name for c in i.columns] for i in model_tables[name].indexes}
        assert _index_differences(name, declared, carried) == [], name
        for c in model_tables[name].columns:
            mc = next(x for x in cols() + mig._base() if getattr(x, "name", None) == c.name)
            assert mc.nullable == c.nullable, f"{name}.{c.name}"


def test_mandate_decider_index_is_partial_and_unique() -> None:
    from app.modules.stakeholders.models import Mandate

    idx = next(i for i in Mandate.__table__.indexes if i.name == "uq_oe_stk_mandate_decider")
    assert idx.unique
    assert "letter = 'D'" in str(idx.dialect_options["postgresql"]["where"])
    assert Mandate.__table__.c.scope.nullable is False


def test_approval_kind_in_model_tuple_and_schema_literal() -> None:
    from app.modules.approval_routes.models import TARGET_KINDS
    from app.modules.approval_routes.schemas import TargetKindLiteral

    assert "stakeholder_commitment" in TARGET_KINDS
    assert "stakeholder_commitment" in typing.get_args(TargetKindLiteral)


def test_permissions_register() -> None:
    from app.core.permissions import permission_registry
    from app.modules.stakeholders.permissions import register_stakeholder_permissions

    register_stakeholder_permissions()
    for perm in (
        "stakeholders.read",
        "stakeholders.edit",
        "stakeholders.read_personal",
        "organisation.manage",
        "stakeholders.catalogue",
    ):
        assert permission_registry.role_has_permission("admin", perm) or permission_registry.role_has_permission(
            "manager", perm
        ), perm
    assert permission_registry.role_has_permission("viewer", "stakeholders.read")
    assert not permission_registry.role_has_permission("viewer", "organisation.manage")
    assert not permission_registry.role_has_permission("editor", "stakeholders.read_personal")


_ERR = re.compile(r"""(?:StakeholderError|not_found|conflict|forbidden)\(\s*["']([a-z_]+)["']""")


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_error_code_raised_has_a_message(locale: str) -> None:
    from app.modules.stakeholders.messages import is_key_present

    codes = set()
    for f in ("service.py", "router.py"):
        codes |= set(_ERR.findall((_MODULE / f).read_text(encoding="utf-8")))
    codes |= {"approval_pending", "no_commitment_route"}
    # Refusals of module 1 that pass through this module's routes with their own code.
    codes |= {
        "catalogue_retired",
        "document_not_found",
        "not_area_owner",
        "document_read_only",
        "document_not_binding",
        "no_pending_revision",
        "change_request_not_open",
        "no_decision_route",
    }
    missing = sorted(c for c in codes if not is_key_present(f"stakeholders.errors.{c}", locale))
    assert missing == []


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_rule_and_evidence_check_has_messages(locale: str) -> None:
    from app.modules.stakeholders.evidence import CHECKS
    from app.modules.stakeholders.messages import is_key_present
    from app.modules.stakeholders.validators import STAKEHOLDER_RULES

    assert len(STAKEHOLDER_RULES) == 11
    for rule in STAKEHOLDER_RULES:
        for part in ("fail", "suggestion"):
            assert is_key_present(f"stakeholders.rules.{rule.key}.{part}", locale), rule.key
    for code in CHECKS:
        assert is_key_present(f"stakeholders.evidence.{code}", locale), code


def test_no_issue_register_words_in_model_names() -> None:
    src = (_MODULE / "models.py").read_text(encoding="utf-8")
    names = re.findall(r"^class (\w+)\(Base\)", src, re.M) + re.findall(r'__tablename__ = "([^"]+)"', src)
    words = ("ncr", "punch", "defect", "snag", "issue", "clash", "nonconform", "observation")
    assert not [n for n in names if any(w in n.lower() for w in words)]


def test_every_audit_call_uses_keywords_log_activity_accepts() -> None:
    """``_audit`` forwards its keywords to ``log_activity``; an unknown one is a TypeError on every write."""
    import inspect

    from app.core.audit_log import log_activity

    accepted = set(inspect.signature(log_activity).parameters)
    tree = ast.parse((_MODULE / "service.py").read_text(encoding="utf-8"))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_audit"
    ]
    assert len(calls) >= 20
    unknown = sorted({k.arg for c in calls for k in c.keywords if k.arg and k.arg not in accepted})
    assert unknown == []


@pytest.mark.asyncio
async def test_subscribers_come_back_after_the_bus_was_emptied(monkeypatch) -> None:
    from app.core.events import event_bus
    from app.modules.stakeholders import events

    saved = {name: list(handlers) for name, handlers in event_bus._handlers.items()}
    calls: list[tuple[str, dict]] = []

    async def trigger(name: str, data: dict, session_factory=None) -> int:
        calls.append((name, data))
        return 0

    monkeypatch.setattr(events, "handle_trigger", trigger)
    try:
        events.register_stakeholder_subscribers()
        # What a test or an in-process restart does: the handlers go, the bus object stays.
        event_bus._handlers.clear()
        events.register_stakeholder_subscribers()
        events.register_stakeholder_subscribers()
        assert event_bus._handlers[events.GATE_SUBMITTED].count(events._on_trigger) == 1
        assert event_bus._handlers["approval_routes.instance.completed"].count(events._on_completed) == 1
        await event_bus.publish(events.GATE_SUBMITTED, {"project_id": "p"})
    finally:
        event_bus._handlers.clear()
        event_bus._handlers.update(saved)
    assert calls == [(events.GATE_SUBMITTED, {"project_id": "p"})]
