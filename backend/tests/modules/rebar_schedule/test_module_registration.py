# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The module is discovered, mountable, and registers what it says it does.

A module that fails to import drops out of the registry silently rather than
raising, so "it is in the folder" is not evidence that it loads.
"""

from app.core.module_loader import ModuleLoader
from app.core.permissions import Role, permission_registry
from app.core.validation.engine import rule_registry
from app.database import Base
from app.modules.rebar_schedule import manifest as module_manifest
from app.modules.rebar_schedule import on_startup, router
from app.modules.rebar_schedule.models import RebarScheduleImport, RebarShape
from app.modules.rebar_schedule.validators import RULE_SET, RULES

EXPECTED_PERMISSIONS = {
    "rebar_schedule.read": Role.VIEWER,
    "rebar_schedule.import": Role.EDITOR,
    "rebar_schedule.delete": Role.MANAGER,
}


def test_the_loader_discovers_the_module() -> None:
    found = {found.name: found for found in ModuleLoader().discover()}
    assert "oe_rebar_schedule" in found
    discovered = found["oe_rebar_schedule"]
    assert discovered.display_name == module_manifest.manifest.display_name
    assert discovered.auto_install is True


def test_the_manifest_declares_the_modules_it_actually_uses() -> None:
    """Projects and users, because every route is project-scoped and permissioned."""
    assert set(module_manifest.manifest.depends) == {"oe_users", "oe_projects"}


def test_the_router_mounts_under_the_hyphenated_module_name() -> None:
    """The loader derives ``/api/v1/rebar-schedule`` from the directory name."""
    paths = {getattr(route, "path", "") for route in router.router.routes}
    assert "/super-groups/" in paths
    assert "/imports/" in paths
    assert "/imports/{import_id}/export" in paths


def test_both_tables_are_registered_on_the_shared_metadata() -> None:
    assert RebarScheduleImport.__tablename__ in Base.metadata.tables
    assert RebarShape.__tablename__ in Base.metadata.tables


def test_the_table_names_follow_the_projects_convention() -> None:
    assert RebarScheduleImport.__tablename__.startswith("oe_rebar_")
    assert RebarShape.__tablename__.startswith("oe_rebar_")


async def test_startup_registers_the_permissions_and_the_rule_set() -> None:
    await on_startup()

    granted = permission_registry.list_all()
    for permission, role in EXPECTED_PERMISSIONS.items():
        assert granted.get(permission) == role, permission

    registered = {rule.rule_id for rule in rule_registry.get_rules_for_sets([RULE_SET])}
    assert registered == {rule.rule_id for rule in RULES}


async def test_startup_is_idempotent() -> None:
    """The loader may call it again after a module is toggled off and on."""
    await on_startup()
    await on_startup()
    registered = [rule.rule_id for rule in rule_registry.get_rules_for_sets([RULE_SET])]
    assert len(registered) == len(set(registered)) == len(RULES)
