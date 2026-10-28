# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design management wiring without a database: registration, router guards, messages, migration shape.

Database behaviour (counters under load, releases into transmittals, IDOR over
HTTP, migration up/down/up) lives in ``tests/pg/test_design_*.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.design_management.validators import DESIGN_RULE_SET, DESIGN_RULES

_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "design_management"
_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def test_permissions_register_the_five_keys() -> None:
    from app.core.permissions import Role, permission_registry
    from app.modules.design_management.permissions import register_design_permissions

    register_design_permissions()
    assert permission_registry.role_has_permission(Role.VIEWER.value, "design.read")
    assert permission_registry.role_has_permission(Role.EDITOR.value, "design.edit")
    assert permission_registry.role_has_permission(Role.EDITOR.value, "design.release")
    assert not permission_registry.role_has_permission(Role.EDITOR.value, "design.manage")
    assert not permission_registry.role_has_permission(Role.EDITOR.value, "design.approve")
    assert permission_registry.role_has_permission(Role.MANAGER.value, "design.approve")


def test_rules_register_under_the_rule_set_with_the_spec_ids() -> None:
    from app.core.validation.engine import rule_registry
    from app.modules.design_management.validators import register_design_rules

    register_design_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([DESIGN_RULE_SET])}
    assert ids == {
        f"design_management.{k}"
        for k in (
            "wbs_code_unique",
            "wbs_reference_resolves",
            "drawing_number_matches_scheme",
            "drawing_number_parts_consistent",
            "drawing_originator_known",
            "title_block_matches_number",
            "release_revisions_suitable",
            "deliverable_complete_for_phase",
            "report_independent_check",
            "not_required_has_rationale",
            "permit_package_complete",
            "permit_content_current",
            "approval_by_entitled_user",
        )
    }


def test_approval_routes_know_both_design_target_kinds() -> None:
    from typing import get_args

    from app.modules.approval_routes.models import TARGET_KINDS
    from app.modules.approval_routes.schemas import TargetKindLiteral

    for kind in ("design_approval_point", "design_release"):
        assert kind in TARGET_KINDS
        assert kind in get_args(TargetKindLiteral)


def test_catalogue_kinds_and_gate_evidence_register_on_startup() -> None:
    import asyncio

    from app.core import cde_naming
    from app.modules.design_management import on_startup
    from app.modules.project_governance.catalogue_kinds import catalogue_kinds
    from app.modules.project_governance.evidence import evidence_providers

    asyncio.run(on_startup())
    assert {"drawing_numbering", "design_reports"} <= set(catalogue_kinds())
    provider = next(p for p in evidence_providers() if p.name == "design_management.phase_readiness")
    assert provider.blocking
    assert "design_management.numbering" in cde_naming._CHECKERS


def _handlers() -> list[ast.AsyncFunctionDef]:
    tree = ast.parse((_MODULE / "router.py").read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr
                in (
                    "get",
                    "post",
                    "put",
                    "patch",
                    "delete",
                )
            ):
                out.append(node)
    return out


def test_every_project_handler_awaits_verify_project_access_first() -> None:
    handlers = _handlers()
    assert len(handlers) > 50
    for fn in handlers:
        awaited = [
            n.value.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Await) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
        ]
        assert "verify_project_access" in awaited, fn.name
        first = next(
            n
            for n in fn.body
            if isinstance(n, ast.Expr | ast.Assign | ast.Return | ast.AnnAssign)
            and "verify_project_access" in ast.unparse(n)
        )
        before = fn.body[: fn.body.index(first)]
        assert all("DesignService" not in ast.unparse(n) for n in before), fn.name


def test_every_handler_declares_a_permission() -> None:
    for fn in _handlers():
        decorators = " ".join(ast.unparse(d) for d in fn.decorator_list)
        assert re.search(r"dependencies=\[(READ|EDIT|RELEASE|MANAGE)\]", decorators), fn.name


def _flatten(node: dict, prefix: str = "") -> set[str]:
    out = set()
    for k, v in node.items():
        key = f"{prefix}.{k}" if prefix else k
        out |= _flatten(v, key) if isinstance(v, dict) else {key}
    return out


def _codes_in_source() -> set[str]:
    codes: set[str] = set()
    pattern = re.compile(
        r'(?:DesignError|not_found|conflict|forbidden|FieldIssue|WbsRuleError)\(\s*"([a-z_]+)"'
        r'|_get\([^)]*?"([a-z_]+_not_found)"'
    )
    for path in _MODULE.glob("*.py"):
        for m in pattern.finditer(path.read_text(encoding="utf-8")):
            codes.add(m.group(1) or m.group(2))
    return codes


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_error_code_and_rule_key_has_a_message(locale: str) -> None:
    keys = _flatten(json.loads((_MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8")))
    missing = sorted(c for c in _codes_in_source() if f"design.errors.{c}" not in keys)
    assert not missing, missing
    for rule in DESIGN_RULES:
        assert f"design.rules.{rule.key}.fail" in keys
        assert f"design.rules.{rule.key}.suggestion" in keys


def test_en_and_de_have_the_same_keys() -> None:
    en = _flatten(json.loads((_MODULE / "messages" / "en.json").read_text(encoding="utf-8")))
    de = _flatten(json.loads((_MODULE / "messages" / "de.json").read_text(encoding="utf-8")))
    assert en == de


@pytest.mark.asyncio
async def test_rules_report_failures_from_a_payload() -> None:
    from app.modules.design_management.catalogue import NUMBERING_KIND, register_kinds
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    register_kinds()
    scheme = get_catalogue_kind(NUMBERING_KIND).get_shipped("iso19650_generic").model_dump(mode="json")
    payload = {
        "scheme": scheme,
        "wbs": [
            {"id": "00000000-0000-0000-0000-000000000001", "code": "1.1"},
            {"id": "00000000-0000-0000-0000-000000000002", "code": "1.1"},
        ],
        "unresolved": [{"module": "boq", "table": "oe_boq_position", "row_id": "x", "value": "9.9"}],
        "drawings": [
            {
                "id": "a",
                "number": "PRJ1-ABC-ZZ-01-DR-A-0001",
                "parts": {},
                "originator": "ABC",
                "title_block_number": "PRJ1-ABC-ZZ-01-DR-A-0002",
            },
            {"id": "b", "number": "BAD", "parts": {}, "originator": None, "legacy_scheme": True},
        ],
        "originators": ["XYZ"],
        "releases": [
            {
                "code": "REL-1",
                "purpose": "for_construction",
                "revisions": [{"id": "00000000-0000-0000-0000-000000000003", "suitability": "S2"}],
            }
        ],
        "deliverables": [{"code": "DL-1", "phase_code": "p", "status": "in_progress", "required": True}],
        "reports": [
            {"code": "R-1", "status": "not_required", "rationale": " "},
            {
                "code": "R-2",
                "status": "accepted",
                "independent_check": "required_by_rule",
                "author_party": "contact:1",
                "checker_party": "contact:1",
                "external_check": False,
                "cycle_state": None,
            },
        ],
        "permits": [{"code": "PP-1", "status": "submitted", "missing": 2, "superseded_content": True}],
        "approval_points": [{"code": "AP-1", "status": "approved", "decided_by": "u", "submitted_by": "u"}],
        "four_eyes": True,
    }
    context = ValidationContext(data=payload, metadata={"locale": "en"})
    failed = set()
    for cls in DESIGN_RULES:
        for r in await cls().validate(context):
            if not r.passed:
                failed.add(cls.key)
                assert r.message and "design.rules" not in r.message
    assert failed == {
        "wbs_code_unique",
        "wbs_reference_resolves",
        "drawing_number_matches_scheme",
        "drawing_number_parts_consistent",
        "drawing_originator_known",
        "title_block_matches_number",
        "report_independent_check",
        "release_revisions_suitable",
        "deliverable_complete_for_phase",
        "not_required_has_rationale",
        "permit_package_complete",
        "permit_content_current",
        "approval_by_entitled_user",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "module", "phase"),
    [("de", "Finanzen", "Ausführung"), ("en", "Finance", "Execution")],
)
async def test_warning_texts_name_the_module_and_phase_not_their_codes(locale: str, module: str, phase: str) -> None:
    """A reference and a deliverable warn in the viewer's language; a code the bundle lacks stays as written."""
    payload = {
        "unresolved": [
            {"module": "finance", "table": "oe_finance_budget", "row_id": "x", "value": "210"},
            {"module": "plugin_x", "table": "t", "row_id": "y", "value": "9"},
        ],
        "deliverables": [{"code": "DL-4", "phase_code": "execution", "status": "in_progress", "required": True}],
    }
    context = ValidationContext(data=payload, metadata={"locale": locale})
    by_key = {cls.key: await cls().validate(context) for cls in DESIGN_RULES}
    refs = [r.message for r in by_key["wbs_reference_resolves"]]
    assert any(module in m and "210" in m for m in refs)
    assert any("plugin_x" in m for m in refs)
    assert not any("finance" in m for m in refs)
    [deliverable] = by_key["deliverable_complete_for_phase"]
    assert phase in deliverable.message and "execution" not in deliverable.message


def _migration():
    path = _VERSIONS / "v74_design_management.py"
    spec = importlib.util.spec_from_file_location("v74_design_management", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chains_onto_governance_and_names_every_model_table() -> None:
    from app.modules.design_management.models import ALL_MODELS

    mig = _migration()
    assert mig.revision == "v74_design_management"
    # The parent is the integration branch's to order; what must hold here is that it is a real revision.
    assert isinstance(mig.down_revision, str)
    assert (_VERSIONS / f"{mig.down_revision}.py").is_file(), mig.down_revision
    assert [t for t, _c, _i in mig._TABLES] == [m.__tablename__ for m in ALL_MODELS]


def _hook_index_names(table) -> set[str]:
    """Every index name the platform's ``after_create`` hook may add to a table."""
    from app.core.pg_optimizations import GIN_JSON_COLUMNS, _index_name

    names = {_index_name(table.name, [c.name]) for c in table.columns if c.foreign_keys}
    for pair in (["project_id", "created_at"], ["project_id", "status"]):
        if set(pair) <= set(table.c.keys()):
            names.add(_index_name(table.name, pair))
    names |= {_index_name(table.name, [c.name], gin=True) for c in table.columns if c.name in GIN_JSON_COLUMNS}
    return names


def test_the_hook_index_names_are_the_hooks_own() -> None:
    """The rule above must name what the hook really builds, or it would hide a missing index."""
    from app.core.pg_optimizations import _desired_indexes
    from app.modules.design_management.models import ALL_MODELS

    for model in ALL_MODELS:
        table = model.__table__
        before = set(table.indexes)
        try:
            built = {ix.name for ix in _desired_indexes(table)}
        finally:
            # Building an index attaches it to the shared metadata; leave the table as it was found.
            table.indexes.difference_update(set(table.indexes) - before)
        assert built <= _hook_index_names(table), (table.name, sorted(built - _hook_index_names(table)))


def _undeclared_indexes(table, declared: set[str]) -> set[str]:
    """Indexes on the model that no revision declares and that the platform's hook does not explain."""
    from sqlalchemy import Index

    on_model = {i.name for i in table.indexes if isinstance(i, Index)}
    return on_model - declared - _hook_index_names(table)


def test_no_own_index_repeats_a_hook_index_under_another_name() -> None:
    """The hook would then build the same index twice on every install."""
    from sqlalchemy import Index

    from app.core.pg_optimizations import _desired_indexes
    from app.modules.design_management.models import ALL_MODELS

    for model in ALL_MODELS:
        table = model.__table__
        before = set(table.indexes)
        own = {tuple(c.name for c in i.columns): i.name for i in before if isinstance(i, Index) and not i.unique}
        try:
            built = {tuple(c.name for c in ix.columns): ix.name for ix in _desired_indexes(table)}
        finally:
            table.indexes.difference_update(set(table.indexes) - before)
        repeated = {cols: (own[cols], name) for cols, name in built.items() if cols in own and own[cols] != name}
        assert not repeated, (table.name, repeated)


def test_a_stray_index_is_not_excused_by_the_hook() -> None:
    """With the hook's indexes attached, only they are set aside: one more index is still a difference."""
    from sqlalchemy import Column, ForeignKey, Index, MetaData, String, Table

    from app.core.pg_optimizations import _desired_indexes

    meta = MetaData()
    Table("oe_probe_parent", meta, Column("id", String(36), primary_key=True))
    table = Table(
        "oe_probe_child",
        meta,
        Column("id", String(36), primary_key=True),
        Column("project_id", String(36), ForeignKey("oe_probe_parent.id")),
        Column("status", String(20)),
        Column("code", String(20)),
    )
    declared = {Index("ix_probe_child_code", table.c.code).name}
    hook = {ix.name for ix in _desired_indexes(table)}
    assert hook, "the probe table must be one the hook indexes"
    assert _undeclared_indexes(table, declared) == set()
    Index("ix_probe_child_status_stray", table.c.status)
    assert _undeclared_indexes(table, declared) == {"ix_probe_child_status_stray"}


def test_migration_columns_and_names_match_the_models() -> None:
    """Same columns, nullability, constraint and index names as ``create_all`` (no drift between installs)."""
    from sqlalchemy import Index, UniqueConstraint

    from app.modules.design_management.models import ALL_MODELS

    mig = _migration()
    by_table = {t: (cols, idx) for t, cols, idx in mig._TABLES}
    for model in ALL_MODELS:
        table = model.__table__
        cols, idx = by_table[table.name]
        items = [*mig._base(), *cols()]

        def shape(c) -> tuple:
            return (c.nullable, type(c.type).__name__, getattr(c.type, "length", None))

        mig_cols = {c.name: shape(c) for c in items if hasattr(c, "nullable") and hasattr(c, "type")}
        model_cols = {c.name: shape(c) for c in table.columns}
        assert mig_cols == model_cols, table.name
        mig_uq = {c.name for c in items if isinstance(c, UniqueConstraint)}
        model_uq = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}
        assert mig_uq == model_uq, table.name
        partial = {n: (cols, where) for n, t, cols, where in mig._PARTIAL_UNIQUE if t == table.name}
        declared = {n for n, _ in idx} | set(partial)
        on_model = {i.name for i in table.indexes if isinstance(i, Index)}
        # ``create_all`` runs the platform's index hook, which attaches its own indexes to the shared
        # metadata; whether it ran before this test depends on the order of the run. No revision creates
        # those, so they are set aside by the hook's own naming rule, not by a list of names.
        assert declared <= on_model, (table.name, sorted(declared - on_model))
        assert _undeclared_indexes(table, declared) == set(), table.name
        for index in table.indexes:
            if index.name in partial:
                cols, where = partial[index.name]
                assert index.unique and [c.name for c in index.columns] == cols
                assert str(index.dialect_options["postgresql"]["where"]) == where
        mig_fk = {fk.name for c in items if hasattr(c, "foreign_keys") for fk in c.foreign_keys}
        model_fk = {fk.name for c in table.columns for fk in c.foreign_keys}
        assert mig_fk == model_fk, table.name
