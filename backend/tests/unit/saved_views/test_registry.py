"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Registry validation - the column whitelist's registration-time guards.

Pure-unit (no DB): these lock down that an entity cannot be registered without a
valid scoper, that a FieldSpec pointing at a non-existent column is refused, and
that grouping is only allowed on indexed columns.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import pytest

from app.modules.saved_views.errors import RegistrationError
from app.modules.saved_views.registry import (
    EntityRegistry,
    FieldSpec,
    QueryableEntity,
)
from app.modules.saved_views.scoper import project_member_scoper


def _project_model():
    from app.modules.projects.models import Project

    return Project


def _entity(**overrides) -> QueryableEntity:
    base = {
        "entity_type": "toy",
        "model": _project_model(),
        "fields": {"name": FieldSpec(name="name", column="name", kind="string")},
        "scoper": project_member_scoper,
        "project_fk_column": "id",
        "default_sort": ("name", "asc"),
    }
    base.update(overrides)
    return QueryableEntity(**base)


def test_register_and_get():
    reg = EntityRegistry()
    reg.register(_entity())
    assert reg.get("toy") is not None
    assert "toy" in reg.list_types()


def test_duplicate_entity_type_rejected():
    reg = EntityRegistry()
    reg.register(_entity())
    with pytest.raises(RegistrationError):
        reg.register(_entity())


def test_missing_scoper_rejected():
    reg = EntityRegistry()
    with pytest.raises(RegistrationError):
        reg.register(_entity(scoper=None))


def test_field_column_must_be_real_column():
    reg = EntityRegistry()
    bad = _entity(fields={"ghost": FieldSpec(name="ghost", column="does_not_exist", kind="string")})
    with pytest.raises(RegistrationError):
        reg.register(bad)


def test_groupable_on_non_indexed_column_rejected():
    reg = EntityRegistry()
    # Project.description has no index, so groupable must be refused.
    bad = _entity(
        fields={
            "name": FieldSpec(name="name", column="name", kind="string"),
            "description": FieldSpec(name="description", column="description", kind="string", groupable=True),
        }
    )
    with pytest.raises(RegistrationError):
        reg.register(bad)


def test_groupable_on_indexed_column_accepted():
    reg = EntityRegistry()
    # Project.owner_id carries index=True, so grouping on it is allowed.
    ok = _entity(
        fields={
            "name": FieldSpec(name="name", column="name", kind="string"),
            "owner_id": FieldSpec(name="owner_id", column="owner_id", kind="uuid", groupable=True),
        }
    )
    reg.register(ok)
    assert reg.get("toy") is not None


def test_entity_without_project_pin_rejected():
    reg = EntityRegistry()
    bad = _entity(project_fk_column=None, project_subquery=None)
    with pytest.raises(RegistrationError):
        reg.register(bad)


def test_default_sort_must_be_sortable_field():
    reg = EntityRegistry()
    bad = _entity(default_sort=("not_a_field", "asc"))
    with pytest.raises(RegistrationError):
        reg.register(bad)


def test_builtin_entities_register_cleanly():
    """The three built-in adapters build and validate without error."""
    from app.modules.saved_views.entities import boq_entity, finance_entity, projects_entity

    reg = EntityRegistry()
    reg.register(projects_entity.build_entity())
    reg.register(boq_entity.build_entity())
    reg.register(finance_entity.build_entity())
    assert set(reg.list_types()) == {"project", "boq_position", "ledger_entry"}
