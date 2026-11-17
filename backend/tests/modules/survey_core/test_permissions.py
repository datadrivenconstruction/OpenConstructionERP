# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who may read, write and confirm in the survey register (no database)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.permissions import ROLE_ALIASES, Role, permission_registry
from app.modules.survey_core.permissions import (
    CONFIRM,
    can_confirm,
    register_survey_permissions,
    require_survey_confirm,
)


@pytest.fixture(autouse=True)
def _registered() -> None:
    register_survey_permissions()


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        ("admin", True),
        ("manager", True),
        ("surveyor", True),
        ("Surveyor", True),
        (" SURVEYOR ", True),
        ("editor", False),
        ("estimator", False),
        ("quantity_surveyor", False),
        ("viewer", False),
        ("guest", False),
        ("", False),
        (None, False),
        ("nonsense", False),
    ],
)
def test_who_may_confirm(role: str | None, allowed: bool) -> None:
    assert can_confirm({"role": role}) is allowed


def test_a_token_without_a_role_may_not_confirm() -> None:
    assert can_confirm({}) is False


def test_an_explicit_grant_in_the_token_lets_a_viewer_confirm() -> None:
    assert can_confirm({"role": "viewer", "permissions": [CONFIRM]}) is True
    assert can_confirm({"role": "viewer", "permissions": ["survey.read"]}) is False
    assert can_confirm({"role": "viewer", "permissions": None}) is False


def test_the_registry_levels_are_read_viewer_write_editor_confirm_manager() -> None:
    for role, read, write, confirm in [
        ("viewer", True, False, False),
        ("editor", True, True, False),
        ("surveyor", True, True, False),
        ("manager", True, True, True),
        ("admin", True, True, True),
    ]:
        assert permission_registry.role_has_permission(role, "survey.read") is read, role
        assert permission_registry.role_has_permission(role, "survey.write") is write, role
        assert permission_registry.role_has_permission(role, CONFIRM) is confirm, role


def test_the_surveyor_alias_is_an_editor_so_it_never_outranks_one_elsewhere() -> None:
    assert ROLE_ALIASES["surveyor"] is Role.EDITOR
    assert not permission_registry.role_has_permission("surveyor", "projects.delete")


def test_registering_twice_changes_nothing() -> None:
    before = permission_registry.role_has_permission("manager", CONFIRM)
    register_survey_permissions()
    assert permission_registry.role_has_permission("manager", CONFIRM) is before


@pytest.mark.asyncio
async def test_the_dependency_answers_403_naming_the_permission() -> None:
    with pytest.raises(HTTPException) as err:
        await require_survey_confirm({"role": "editor"})
    assert err.value.status_code == 403
    assert CONFIRM in err.value.detail
    assert await require_survey_confirm({"role": "surveyor"}) is None
