# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``default_columns`` has to resolve, or a run silently returns fewer columns.

A spec that names its own columns is checked by ``FilterSpec.bind``. The
default set is not: it is read straight out of the registration when a spec
asks for no columns, and ``_serialize_row`` drops a name it cannot resolve
without a word. The result is a response short a column and a CSV export whose
header carries a cell that is always empty - the kind of wrong that nobody
reports because it looks like missing data.

The registration is therefore where it has to fail, and it has to fail the boot
rather than a request: an entity is registered once at startup, so a bad
default column that only surfaced on use would sit there for a release.

These tests use the real registry and clear only the entity they registered, so
they cannot disturb the built-in registrations another module test relies on.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.saved_views.errors import RegistrationError
from app.modules.saved_views.registry import (
    FieldSpec,
    QueryableEntity,
    entity_registry,
    register_queryable_entity,
)
from app.modules.saved_views.scoper import project_member_scoper

ENTITY_TYPE = "saved_view_default_columns_probe"


def _entity(default_columns: tuple[str, ...], **field_overrides: Any) -> QueryableEntity:
    """A registrable entity whose default column set is under test."""
    from app.modules.saved_views.models import SavedView

    fields = {
        "name": FieldSpec(name="name", column="name", kind="string"),
        "share_scope": FieldSpec(name="share_scope", column="share_scope", kind="string"),
        "created_at": FieldSpec(name="created_at", column="created_at", kind="date"),
    }
    fields.update(field_overrides)
    return QueryableEntity(
        entity_type=ENTITY_TYPE,
        model=SavedView,
        fields=fields,
        scoper=project_member_scoper,
        default_sort=("created_at", "desc"),
        project_fk_column="project_id",
        default_columns=default_columns,
    )


@pytest.fixture(autouse=True)
def _drop_probe_entity():
    """Remove only this module's entity, leaving the built-ins registered."""
    yield
    entity_registry._entities.pop(ENTITY_TYPE, None)  # noqa: SLF001 - narrow test cleanup


def test_resolvable_default_columns_register() -> None:
    """The good case still registers, so the gate is not simply refusing everything."""
    register_queryable_entity(_entity(("name", "share_scope")))
    assert entity_registry.get(ENTITY_TYPE) is not None


def test_unknown_default_column_fails_the_registration() -> None:
    """A name that is not whitelisted would be dropped in silence at run time."""
    with pytest.raises(RegistrationError) as excinfo:
        register_queryable_entity(_entity(("name", "unit_rate")))
    assert "unit_rate" in str(excinfo.value)
    assert entity_registry.get(ENTITY_TYPE) is None


def test_unselectable_default_column_fails_the_registration() -> None:
    """Whitelisted is not enough; the default set has to be returnable."""
    hidden = FieldSpec(name="share_scope", column="share_scope", kind="string", selectable=False)
    with pytest.raises(RegistrationError) as excinfo:
        register_queryable_entity(_entity(("name", "share_scope"), share_scope=hidden))
    assert "not selectable" in str(excinfo.value)
    assert entity_registry.get(ENTITY_TYPE) is None


def test_every_shipped_entity_has_resolvable_default_columns() -> None:
    """The built-in registrations pass the gate they were added under.

    Registering the built-ins is what boots the app, so a shipped entity that
    failed this check would take the whole platform down rather than one view.
    """
    from app.modules.saved_views.entities import register_builtin_entities

    register_builtin_entities()
    for entity_type, entity in entity_registry.all().items():
        for column in entity.default_columns:
            field_spec = entity.fields.get(column)
            assert field_spec is not None, f"{entity_type}.{column} is not whitelisted"
            assert field_spec.selectable, f"{entity_type}.{column} is not selectable"
