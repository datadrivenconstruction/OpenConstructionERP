# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project governance without a database: registration, router guards, error
contract, validation rules and the tenant catalogue validator.

Database behaviour (decisions, locks, routes, tenants) is in
``tests/pg/test_governance_*.py``.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.validation.engine import ValidationContext
from app.modules.project_governance import router as gov_router
from app.modules.project_governance.catalogue import (
    InvalidCatalogueError,
    catalogue_from_body,
    get_catalogue,
    label_of,
)
from app.modules.project_governance.catalogue_store import content_hash, diff_bodies, empty_body, shipped_body
from app.modules.project_governance.errors import GovernanceError
from app.modules.project_governance.validators import GOVERNANCE_RULES

# ── registration ──


def test_permissions_register_the_four_keys() -> None:
    from app.core.permissions import Role, permission_registry
    from app.modules.project_governance.permissions import register_governance_permissions

    register_governance_permissions()
    assert permission_registry.role_has_permission(Role.VIEWER.value, "governance.read")
    assert permission_registry.role_has_permission(Role.EDITOR.value, "governance.edit")
    assert not permission_registry.role_has_permission(Role.EDITOR.value, "governance.decide")
    assert not permission_registry.role_has_permission(Role.EDITOR.value, "governance.manage")
    assert permission_registry.role_has_permission(Role.MANAGER.value, "governance.decide")


def test_rules_register_under_the_rule_set() -> None:
    from app.core.validation.engine import rule_registry
    from app.modules.project_governance.validators import GOVERNANCE_RULE_SET, register_governance_rules

    register_governance_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([GOVERNANCE_RULE_SET])}
    assert ids == {cls.rule_id for cls in GOVERNANCE_RULES}
    assert len(ids) == 7


def test_approval_routes_know_both_target_kinds() -> None:
    from typing import get_args

    from app.modules.approval_routes.models import TARGET_KINDS
    from app.modules.approval_routes.schemas import TargetKindLiteral

    for kind in ("phase_gate", "frame_change"):
        assert kind in TARGET_KINDS
        assert kind in get_args(TargetKindLiteral)


def test_manifest_name_matches_directory() -> None:
    from app.modules.project_governance.manifest import manifest

    assert manifest.name == "oe_project_governance"
    assert "oe_approval_routes" in manifest.depends


# ── router guards ──


def _handlers() -> list[ast.AsyncFunctionDef]:
    tree = ast.parse(Path(inspect.getfile(gov_router)).read_text(encoding="utf-8"))
    return [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.decorator_list]


def test_every_project_route_calls_verify_project_access_first() -> None:
    project_routes = [h for h in _handlers() if any(a.arg == "project_id" for a in h.args.args)]
    assert len(project_routes) >= 25
    missing = []
    for h in project_routes:
        # ast.walk is breadth-first, so "first" has to be taken by source position.
        awaits = [n for n in ast.walk(h) if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)]
        first_await = min(awaits, key=lambda n: (n.lineno, n.col_offset), default=None)
        name = getattr(getattr(first_await, "value", None), "func", None)
        if getattr(name, "id", None) != "verify_project_access":
            missing.append(h.name)
    assert missing == []


def test_every_route_declares_a_governance_permission() -> None:
    for route in gov_router.router.routes:
        perms = [getattr(d.dependency, "permission", "") for d in route.dependencies]
        assert any(p.startswith("governance.") for p in perms), route.path


def test_project_routes_are_nested_under_projects() -> None:
    for route in gov_router.router.routes:
        assert route.path.startswith(("/projects/{project_id}/", "/catalogues")), route.path


def test_decide_reopen_and_waive_need_the_decide_permission() -> None:
    by_name = {r.name: r for r in gov_router.router.routes}
    for name in ("decide_gate", "reopen_gate", "waive_condition", "resume_gate"):
        perms = {getattr(d.dependency, "permission", "") for d in by_name[name].dependencies}
        assert "governance.decide" in perms, name


# ── error contract ──


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404, 409, 422])
async def test_errors_carry_code_message_key_and_violations(status: int) -> None:
    async def boom():
        raise GovernanceError("area_without_owner", status, violations=[{"code": "area_without_owner"}])

    with pytest.raises(HTTPException) as exc:
        await gov_router._run(boom())
    assert exc.value.status_code == status
    assert exc.value.detail["code"] == "area_without_owner"
    assert exc.value.detail["message_key"] == "governance.errors.area_without_owner"
    assert exc.value.detail["message"]
    assert exc.value.detail["violations"] == [{"code": "area_without_owner"}]


def test_every_error_code_the_service_raises_has_a_message() -> None:
    import json
    import re

    import app.modules.project_governance as pkg

    root = Path(pkg.__file__).parent
    en = json.loads((root / "messages" / "en.json").read_text(encoding="utf-8"))["governance"]["errors"]
    raised: set[str] = set()
    for f in ("service.py", "catalogue_store.py"):
        text = (root / f).read_text(encoding="utf-8")
        raised |= set(re.findall(r'(?:GovernanceError|conflict|forbidden|not_found)\(\s*"([a-z_]+)"', text))
    assert raised, "pattern found nothing"
    assert sorted(raised - set(en)) == []


# ── validation rules: each rule fails on its case and passes without it ──


def _ctx(**data) -> ValidationContext:
    return ValidationContext(data={"today": "2026-10-11", **data}, metadata={"locale": "en"})


CASES = [
    (
        "project_governance.area_has_owner",
        {"areas": [{"code": "A", "owner_user_id": None, "applicable": True}]},
        {"areas": [{"code": "A", "owner_user_id": "u", "applicable": True}]},
    ),
    (
        "project_governance.required_documents_defined",
        {"areas": [{"code": "A"}], "gates": [{"code": "G1", "status": "in_preparation"}], "documents": []},
        {
            "areas": [{"code": "A"}],
            "gates": [{"code": "G1", "status": "in_preparation"}],
            "documents": [{"area_code": "A", "required_at_gates": ["G1"]}],
        },
    ),
    (
        "project_governance.binding_document_unchanged",
        {"documents": [{"id": "d", "status": "binding", "bound_revision_id": "r1", "current_revision_id": "r2"}]},
        {"documents": [{"id": "d", "status": "binding", "bound_revision_id": "r1", "current_revision_id": "r1"}]},
    ),
    (
        "project_governance.conditions_not_overdue",
        {"conditions": [{"id": "c", "status": "open", "due_date": "2026-10-01"}]},
        {"conditions": [{"id": "c", "status": "open", "due_date": "2026-10-30"}]},
    ),
    (
        "project_governance.gate_date_after_previous",
        {
            "gates": [
                {"code": "G1", "sort_order": 1, "target_date": "2026-12-01"},
                {"code": "G2", "sort_order": 2, "target_date": "2026-11-01"},
            ]
        },
        {
            "gates": [
                {"code": "G1", "sort_order": 1, "target_date": "2026-11-01"},
                {"code": "G2", "sort_order": 2, "target_date": "2026-12-01"},
            ]
        },
    ),
    (
        "project_governance.decision_by_entitled_user",
        {"decisions": [{"gate_code": "G1", "decided_by": "u", "four_eyes": True, "owner_ids": ["u"]}]},
        {"decisions": [{"gate_code": "G1", "decided_by": "v", "four_eyes": True, "owner_ids": ["u"]}]},
    ),
    (
        "project_governance.not_applicable_has_rationale",
        {"areas": [{"code": "A", "applicable": False, "na_rationale": ""}]},
        {"areas": [{"code": "A", "applicable": False, "na_rationale": "No BIM scope"}]},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_id", "failing", "passing"), CASES, ids=[c[0] for c in CASES])
async def test_rule_fails_on_its_case_and_passes_on_the_fix(rule_id: str, failing: dict, passing: dict) -> None:
    rule = next(cls() for cls in GOVERNANCE_RULES if cls.rule_id == rule_id)
    bad = await rule.validate(_ctx(**failing))
    good = await rule.validate(_ctx(**passing))
    assert bad and not any(r.passed for r in bad)
    assert good and all(r.passed for r in good)
    assert "{" not in bad[0].message


# ── tenant catalogues: the same validator as shipped files ──


def _clone() -> dict:
    body = shipped_body(get_catalogue("neutral"))
    body["id"] = "acme"
    body["labels"] = {"en": "Acme model"}
    return body


def test_a_clone_of_a_shipped_catalogue_is_a_valid_tenant_catalogue() -> None:
    cat = catalogue_from_body(_clone(), source="tenant", origin="test")
    assert cat.id == "acme"
    assert len(cat.phases) == len(get_catalogue("neutral").phases)


def test_the_validator_rejects_a_broken_tenant_draft() -> None:
    body = _clone()
    body["gates"] = body["gates"][1:]  # a gap between the first two phases
    with pytest.raises(InvalidCatalogueError) as exc:
        catalogue_from_body(body, source="tenant", origin="test")
    assert any(e.startswith("gate_missing") for e in exc.value.errors)


def test_a_tenant_item_without_key_or_english_label_is_refused() -> None:
    body = _clone()
    body["phases"][0]["name_key"] = ""
    body["phases"][0]["labels"] = {"de": "Strategie"}
    with pytest.raises(InvalidCatalogueError) as exc:
        catalogue_from_body(body, source="tenant", origin="test")
    assert any(e.startswith("label_missing: phase") for e in exc.value.errors)
    body["phases"][0]["labels"] = {"en": "Strategy", "de": "Strategie"}
    assert catalogue_from_body(body, source="tenant", origin="test")


def test_an_empty_draft_is_not_publishable() -> None:
    with pytest.raises(InvalidCatalogueError):
        catalogue_from_body(empty_body("x", "X"), source="tenant", origin="test")


def test_a_shipped_catalogue_still_needs_keys_in_its_own_namespace() -> None:
    body = _clone()
    with pytest.raises(InvalidCatalogueError) as exc:
        catalogue_from_body(body, source="shipped", origin="test")
    assert any(e.startswith("i18n_key_outside_namespace") for e in exc.value.errors)


def test_label_type_covers_both_sources() -> None:
    assert label_of("governance.catalogue.neutral.name", None) == {
        "key": "governance.catalogue.neutral.name",
        "text": None,
    }
    assert label_of("", {"en": "Acme"}) == {"key": None, "text": {"en": "Acme"}}


def test_content_hash_is_canonical() -> None:
    a = {"x": 1, "y": [1, 2]}
    b = {"y": [1, 2], "x": 1}
    assert content_hash(a) == content_hash(b)
    assert content_hash(a) != content_hash({"x": 2, "y": [1, 2]})


def test_diff_names_added_removed_and_changed_codes() -> None:
    old = _clone()
    new = _clone()
    new["phases"] = new["phases"][:-1]
    new["areas"][0] = {**new["areas"][0], "labels": {"en": "Renamed"}}
    d = diff_bodies(old, new)
    assert d["phases"]["removed"] == [old["phases"][-1]["code"]]
    assert d["areas"]["changed"] == [old["areas"][0]["code"]]
    assert d["gates"] == {"added": [], "removed": [], "changed": []}


# ── catalogue kinds: a later module registers its own kind with one call ──


def test_a_dummy_kind_registers_and_goes_through_the_same_store_paths(tmp_path: Path) -> None:
    import json

    from pydantic import BaseModel, ConfigDict

    from app.modules.project_governance.catalogue_kinds import (
        PHASE_MODEL_KIND,
        CatalogueKind,
        catalogue_kinds,
        get_catalogue_kind,
        register_catalogue_kind,
        unregister_catalogue_kind,
    )

    class Form(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")
        code: str
        labels: dict[str, str] | None = None

    class DeliveryForms(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")
        id: str
        version: int
        labels: dict[str, str] | None = None
        forms: tuple[Form, ...] = ()

    def validate(obj: DeliveryForms, source: str) -> list[str]:
        codes = [f.code for f in obj.forms]
        return ["duplicate_code"] if len(codes) != len(set(codes)) else []

    (tmp_path / "dbb.json").write_text(
        json.dumps({"id": "dbb", "version": 1, "forms": [{"code": "design_bid_build"}]}), encoding="utf-8"
    )
    register_catalogue_kind(
        CatalogueKind(
            kind="dummy_forms", model=DeliveryForms, validator=validate, shipped_dir=tmp_path, diff_groups=("forms",)
        )
    )
    try:
        assert {"dummy_forms", PHASE_MODEL_KIND} <= set(catalogue_kinds())
        spec = get_catalogue_kind("dummy_forms")
        assert spec.get_shipped("dbb").forms[0].code == "design_bid_build"
        good = {"id": "x", "version": 1, "forms": [{"code": "a"}, {"code": "b"}]}
        assert spec.parse_body(good, source="tenant", origin="t").id == "x"
        with pytest.raises(InvalidCatalogueError) as exc:
            spec.parse_body({**good, "forms": [{"code": "a"}, {"code": "a"}]}, source="tenant", origin="t")
        assert exc.value.errors == ["duplicate_code"]
        with pytest.raises(InvalidCatalogueError):
            spec.parse_body({"id": "x", "version": 1, "unknown": 1}, source="tenant", origin="t")
        d = diff_bodies(good, {**good, "forms": [{"code": "a"}]}, spec.diff_groups)
        assert d == {"forms": {"added": [], "removed": ["b"], "changed": []}}
    finally:
        unregister_catalogue_kind("dummy_forms")
    assert "dummy_forms" not in catalogue_kinds()
