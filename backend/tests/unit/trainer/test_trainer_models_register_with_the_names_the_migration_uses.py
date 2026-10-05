# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The trainer models import, register and carry the agreed names.

``create_all`` and the ``v53_trainer_tables`` revision must build the same
schema; the PG lane compares the two on a real database. This file holds the
cheaper half that needs no database: the models import on their own, every
table lands in ``Base.metadata``, every multi-column constraint carries the
explicit name the revision uses (the naming convention only spells
``column_0``), and the two relationships declare the loading strategy the
backend rules require.

It also pins the startup hook: with the academy flag off, ``on_startup``
registers the two permissions and does nothing else.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import Index, UniqueConstraint

from app.database import Base
from app.modules.projects import models as _projects_models  # noqa: F401 - registers the FK target table
from app.modules.trainer import models
from app.modules.users import models as _users_models  # noqa: F401 - registers the FK target table

EXPECTED_TABLES = {
    "oe_trainer_course",
    "oe_trainer_offer",
    "oe_trainer_enrolment",
    "oe_trainer_task_state",
    "oe_trainer_answer",
    "oe_trainer_attempt",
    "oe_trainer_webhook_event",
}

EXPECTED_UNIQUE = {
    "uq_oe_trainer_course_course_key_version",
    "uq_oe_trainer_offer_provider_product_ref_course_key",
    "uq_oe_trainer_enrolment_user_id_course_id",
    "uq_oe_trainer_task_state_enrolment_id_task_id",
    "uq_oe_trainer_answer_enrolment_id_task_id_answer_name",
    "uq_oe_trainer_attempt_enrolment_id_client_attempt_id",
    "uq_oe_trainer_webhook_event_provider_event_id",
}

EXPECTED_COMPOSITE_INDEXES = {
    "ix_oe_trainer_task_state_enrolment_id_task_n",
    "ix_oe_trainer_attempt_enrolment_id_task_id_created_at",
    "ix_oe_trainer_enrolment_project_id_status",
    "ix_oe_trainer_enrolment_project_id_created_at",
}


def _trainer_tables():
    return {name: table for name, table in Base.metadata.tables.items() if name.startswith("oe_trainer_")}


def test_every_trainer_table_is_registered() -> None:
    assert set(_trainer_tables()) == EXPECTED_TABLES


def test_multi_column_constraints_carry_explicit_names() -> None:
    names: set[str] = set()
    for table in _trainer_tables().values():
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                names.add(str(constraint.name))
    assert names == EXPECTED_UNIQUE


def test_composite_indexes_carry_explicit_names() -> None:
    composite = {
        str(index.name)
        for table in _trainer_tables().values()
        for index in table.indexes
        if isinstance(index, Index) and len(index.columns) > 1
    }
    assert composite == EXPECTED_COMPOSITE_INDEXES


def test_the_performance_index_hook_has_nothing_to_add() -> None:
    """``create_all`` runs ``pg_optimizations``; the revision does not.

    The hook adds a btree index per foreign key that is not the left-most
    column of an index, and ``(project_id, created_at)`` / ``(project_id,
    status)`` composites. When the models already declare all of them, both
    paths build the same indexes. Anything listed here exists only on a
    ``create_all`` database.
    """
    from app.core.pg_optimizations import _desired_indexes

    extra = {name: [ix.name for ix in _desired_indexes(table)] for name, table in _trainer_tables().items()}
    assert {name: found for name, found in extra.items() if found} == {}


def test_every_identifier_fits_postgresql() -> None:
    """PostgreSQL truncates identifiers past 63 bytes, which silently breaks name parity."""
    for table in _trainer_tables().values():
        for item in [*table.constraints, *table.indexes]:
            assert item.name is None or len(str(item.name)) <= 63, item.name


def test_foreign_keys_point_where_the_design_says() -> None:
    tables = _trainer_tables()
    found = {
        (name, fk.parent.name, fk.column.table.name, fk.ondelete)
        for name, table in tables.items()
        for fk in table.foreign_keys
    }
    assert found == {
        ("oe_trainer_enrolment", "user_id", "oe_users_user", "CASCADE"),
        ("oe_trainer_enrolment", "course_id", "oe_trainer_course", "RESTRICT"),
        ("oe_trainer_enrolment", "project_id", "oe_projects_project", "SET NULL"),
        ("oe_trainer_task_state", "enrolment_id", "oe_trainer_enrolment", "CASCADE"),
        ("oe_trainer_answer", "enrolment_id", "oe_trainer_enrolment", "CASCADE"),
        ("oe_trainer_attempt", "enrolment_id", "oe_trainer_enrolment", "CASCADE"),
    }


def test_relationships_declare_their_loading_strategy() -> None:
    task_states = models.TrainerEnrolment.__mapper__.relationships["task_states"]
    enrolment = models.TrainerTaskState.__mapper__.relationships["enrolment"]
    assert task_states.lazy == "selectin"
    assert enrolment.lazy == "raise_on_sql"
    assert {r.key for r in models.TrainerEnrolment.__mapper__.relationships} == {"task_states"}


def test_answers_are_stored_as_typed_text_never_as_a_number() -> None:
    """``value_text`` keeps what was typed; a Numeric column would round on the way in."""
    columns = _trainer_tables()["oe_trainer_answer"].columns
    assert columns["value_text"].type.length == 64
    assert {c.name for c in columns} >= {"answer_name", "kind", "value_text", "option_index", "revision"}


def test_the_dropped_view_mode_column_is_not_there() -> None:
    """Decision 3: the backend never tracks the learner's view mode."""
    assert "required_view_mode" not in _trainer_tables()["oe_trainer_enrolment"].columns


@pytest.fixture
def _academy_off(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    monkeypatch.delenv("OE_ACADEMY_MODE", raising=False)
    monkeypatch.delenv("ACADEMY_MODE", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("_academy_off")
def test_startup_with_the_flag_off_only_registers_permissions() -> None:
    from app.core.permissions import Role, permission_registry
    from app.modules import trainer

    asyncio.run(trainer.on_startup())
    assert sorted(permission_registry.list_modules()["trainer"]) == ["trainer.admin", "trainer.learn"]
    assert permission_registry.get_min_role("trainer.learn") == Role.VIEWER
    assert permission_registry.get_min_role("trainer.admin") == Role.ADMIN
