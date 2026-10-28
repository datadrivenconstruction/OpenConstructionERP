"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Wiring of the site-logistics plan extension: permissions, routes, rules, messages."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from app.modules.site_logistics import plan_service, router, validators
from app.modules.site_logistics.messages import translate

MODULE = Path(router.__file__).parent


def _plan_routes() -> list[APIRoute]:
    return [r for r in router.router.routes if isinstance(r, APIRoute) and r.path.startswith("/projects/{project_id}")]


def test_plan_routes_exist() -> None:
    paths = {r.path for r in _plan_routes()}
    for expected in (
        "/projects/{project_id}/stages",
        "/projects/{project_id}/areas/{area_id}/allocations",
        "/projects/{project_id}/balance",
        "/projects/{project_id}/transports",
        "/projects/{project_id}/permits",
        "/projects/{project_id}/customs",
        "/projects/{project_id}/neighbour-issues",
        "/projects/{project_id}/readiness",
        "/projects/{project_id}/export/{register}",
    ):
        assert expected in paths, expected


@pytest.mark.parametrize("route", _plan_routes(), ids=lambda r: f"{sorted(r.methods)[0]} {r.path}")
def test_every_plan_route_checks_project_access(route: APIRoute) -> None:
    source = inspect.getsource(route.endpoint)
    assert "verify_project_access(" in source


def _permissions(route: APIRoute) -> set[str]:
    return {p for d in route.dependant.dependencies if (p := getattr(d.call, "permission", None))}


@pytest.mark.parametrize("route", _plan_routes(), ids=lambda r: f"{sorted(r.methods)[0]} {r.path}")
def test_every_plan_route_requires_a_permission(route: APIRoute) -> None:
    perms = _permissions(route)
    assert perms and all(p.startswith("site_logistics.") for p in perms)
    if route.path.endswith("/validate"):
        # Runs the rules and returns the report; it writes nothing, so reading the plan is enough.
        assert perms == {"site_logistics.read"}
    elif route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
        assert perms & {"site_logistics.write", "site_logistics.approve", "site_logistics.customs"}, perms


def test_permissions_registered() -> None:
    from app.core.permissions import Role, permission_registry
    from app.modules.site_logistics.permissions import register_site_logistics_permissions

    register_site_logistics_permissions()
    assert permission_registry.role_has_permission(Role.MANAGER.value, "site_logistics.customs")
    assert not permission_registry.role_has_permission(Role.EDITOR.value, "site_logistics.customs")
    assert permission_registry.role_has_permission(Role.EDITOR.value, "site_logistics.write")


def test_plan_rules_cover_every_emitted_rule() -> None:
    keys = {r.key for r in validators.PLAN_RULES}
    assert len(keys) == len(validators.PLAN_RULES) == 23
    source = inspect.getsource(plan_service)
    emitted = set(re.findall(r'_finding\(\s*"([a-z_]+)"', source))
    emitted |= {"stage_has_storage", "stage_has_site_setup", "jit_aligned_to_takt"}
    assert emitted <= keys, emitted - keys


def test_plan_rules_registered() -> None:
    from app.core.validation.engine import rule_registry

    validators.register_site_logistics_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets(["site_logistics"])}
    assert {f"site_logistics.{r.key}" for r in validators.PLAN_RULES} <= ids


def _bundle(locale: str) -> dict:
    return json.loads((MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8"))


def _keys(node: dict, prefix: str = "") -> set[str]:
    out = set()
    for k, v in node.items():
        out |= _keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {f"{prefix}{k}"}
    return out


def test_message_bundles_have_identical_keys() -> None:
    assert _keys(_bundle("en")) == _keys(_bundle("de"))


def test_message_placeholders_match_between_locales() -> None:
    en, de = _bundle("en"), _bundle("de")
    for key in _keys(en):
        e = en
        g = de
        for part in key.split("."):
            e, g = e[part], g[part]
        assert set(re.findall(r"{(\w+)}", e)) == set(re.findall(r"{(\w+)}", g)), key


def test_every_error_code_has_a_message() -> None:
    errors = set(_bundle("en")["site_logistics"]["errors"])
    source = "\n".join(p.read_text(encoding="utf-8") for p in MODULE.glob("*.py"))
    used = set(re.findall(r'(?:LogisticsError|not_found|conflict)\(\s*"([a-z_]+)"', source))
    soft = {f"{k}_not_found" for k in re.findall(r'_soft\(\s*"([a-z_]+)"', source)}
    assert (used | soft) - errors == set()


def test_every_finding_code_has_fail_and_suggestion() -> None:
    findings = _bundle("en")["site_logistics"]["findings"]
    source = inspect.getsource(plan_service)
    codes = set(re.findall(r'_finding\(\s*"[a-z_]+",\s*"([a-z_]+)"', source))
    codes |= {
        "stage_without_storage",
        "stage_without_site_setup",
        "permit_expiring",
        "permit_expired",
        "heavy_without_permit",
        "window_outside_permit",
        "jit_too_early",
        "jit_late",
    }
    for code in codes:
        assert set(findings[code]) == {"fail", "suggestion"}, code


def test_evidence_labels_exist() -> None:
    labels = set(_bundle("en")["site_logistics"]["evidence"])
    source = inspect.getsource(plan_service.LogisticsPlanService.readiness)
    assert set(re.findall(r'_item\(\s*"([a-z_]+)"', source)) <= labels


def test_plan_rule_reports_its_findings_in_locale() -> None:
    rule = next(r for r in validators.PLAN_RULES if r.key == "media_capacity_sufficient")()
    finding = {
        "rule": "media_capacity_sufficient",
        "code": "media_capacity_short",
        "severity": "error",
        "ref": "s1",
        "params": {"stage": "S1", "media": "power", "required": "154.000", "contracted": "140.8"},
    }
    ctx = SimpleNamespace(data={"findings": [finding]}, metadata={"locale": "de"})
    [result] = asyncio.run(rule.validate(ctx))
    assert result.passed is False
    assert "154.000" in result.message and "{" not in result.message
    ok = asyncio.run(rule.validate(SimpleNamespace(data={"findings": []}, metadata={})))
    assert [r.passed for r in ok] == [True]
    assert asyncio.run(rule.validate(SimpleNamespace(data={}, metadata={}))) == []


def test_translate_falls_back_to_english() -> None:
    assert translate("site_logistics.errors.code_taken", locale="xx") == translate(
        "site_logistics.errors.code_taken", locale="en"
    )


def test_neighbour_issue_output_carries_what_the_issue_hub_reads() -> None:
    """``frontend/src/features/issues/issueSources.ts`` maps these fields of a neighbour issue."""
    import uuid
    from datetime import UTC, date, datetime

    from app.modules.site_logistics.models import NeighbourIssue

    row = NeighbourIssue(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        kind="noise",
        reported_on=date(2026, 10, 5),
        description="Concrete pump before 07:00",
        owner_user_id=uuid.uuid4(),
        response_due=date(2026, 10, 10),
        state="received",
        created_at=datetime(2026, 10, 5, 8, tzinfo=UTC),
    )
    out = plan_service.complaint_out(row, today=date(2026, 10, 12))
    for field in ("id", "kind", "description", "owner_user_id", "response_due", "state", "overdue", "created_at"):
        assert field in out, field
    assert out["owner_user_id"] == str(row.owner_user_id)
    assert out["overdue"] is True
    json.dumps(out)


def test_neighbour_issues_are_seen_by_the_issue_hub_census() -> None:
    """The register is named so the hub's census finds it, and the hub reads its module."""
    import importlib

    hub = importlib.import_module("tests.unit.test_issue_hub_sources")
    assert "NeighbourIssue" in hub._modules_with_issue_registers().get("site_logistics", [])
    assert hub._SOURCE_TO_MODULE.get("neighbour") == "site_logistics"
