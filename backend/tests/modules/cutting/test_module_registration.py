# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The module is discovered, mountable, and registers what it says it does."""

import json
from pathlib import Path

from app.core.module_loader import ModuleLoader
from app.core.permissions import Role, permission_registry
from app.core.validation.engine import rule_registry
from app.database import Base
from app.modules.cutting import manifest as module_manifest
from app.modules.cutting import on_startup, router
from app.modules.cutting.models import CuttingJob, CuttingPiece, CuttingPlan, CuttingStock
from app.modules.cutting.validators import RULE_SET, RULES

EXPECTED_PERMISSIONS = {
    "cutting.read": Role.VIEWER,
    "cutting.write": Role.EDITOR,
    "cutting.apply": Role.EDITOR,
}

_LOCALES = Path(__file__).resolve().parents[3] / "locales"


def test_the_loader_discovers_the_module() -> None:
    found = {m.name: m for m in ModuleLoader().discover()}
    assert "oe_cutting" in found
    assert found["oe_cutting"].auto_install is True
    assert set(module_manifest.manifest.depends) == {"oe_users", "oe_projects"}


def test_the_router_carries_the_documented_paths() -> None:
    paths = {getattr(route, "path", "") for route in router.router.routes}
    assert {"/jobs/", "/jobs/{job_id}/optimise", "/plans/{plan_id}/export", "/plans/{plan_id}/return-offcuts"} <= paths


def test_all_tables_are_registered_with_the_module_prefix() -> None:
    for model in (CuttingJob, CuttingPiece, CuttingStock, CuttingPlan):
        assert model.__tablename__ in Base.metadata.tables
        assert model.__tablename__.startswith("oe_cutting_")


async def test_startup_registers_the_permissions_and_the_rule_set() -> None:
    await on_startup()
    granted = permission_registry.list_all()
    for permission, role in EXPECTED_PERMISSIONS.items():
        assert granted.get(permission) == role, permission
    registered = {r.rule_id for r in rule_registry.get_rules_for_sets([RULE_SET])}
    assert registered == {rule.rule_id for rule in RULES}


async def test_startup_is_idempotent() -> None:
    await on_startup()
    await on_startup()
    registered = [rule.rule_id for rule in rule_registry.get_rules_for_sets([RULE_SET])]
    assert len(registered) == len(set(registered)) == len(RULES)


def test_every_rule_message_is_translated_in_every_backend_locale() -> None:
    keys = {"cutting.validation.ok"}
    for rule in RULES:
        name = rule.rule_id.split(".", 1)[1]
        keys |= {f"cutting.validation.{name}.fail", f"cutting.validation.{name}.suggestion"}
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        node = data.get("cutting", {}).get("validation", {})
        flat = {"cutting.validation.ok"} if "ok" in node else set()
        for name, value in node.items():
            if isinstance(value, dict):
                flat |= {f"cutting.validation.{name}.{leaf}" for leaf in value}
        assert keys <= flat, f"{path.name} misses {sorted(keys - flat)}"
