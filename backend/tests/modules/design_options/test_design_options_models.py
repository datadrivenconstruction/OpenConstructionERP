"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The two design-option tables: constraints, relationships and cascades.

Covers ``oe_design_options_set`` and ``oe_design_options_option``: their
nullability and foreign keys as materialised in PostgreSQL, the same-module
set <-> option relationship (ordering, loading strategy) and the delete
behaviour on both the ORM path and the raw database path.

Deletion is always asserted with an explicit query. ``session.get()`` reads the
identity map first and happily returns a row that was deleted in the same
session, so it cannot tell a surviving row from a deleted one.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design_options.models import DesignOption, DesignOptionSet
from app.modules.design_options.service import DesignOptionsService
from tests._pg import schema_inspection_engine
from tests.modules.design_options.conftest import (
    make_option,
    make_project,
    make_set,
    make_user,
)

SET_TABLE = "oe_design_options_set"
OPTION_TABLE = "oe_design_options_option"


async def _count(session: AsyncSession, model: type, **filters: uuid.UUID) -> int:
    """Count rows with a real query (never ``session.get``)."""
    stmt = select(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return len((await session.execute(stmt)).scalars().all())


# ── Schema ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def inspector():
    """Reflect the materialised schema of the shared unit database."""
    engine = schema_inspection_engine()
    try:
        yield sa_inspect(engine)
    finally:
        engine.dispose()


def test_set_required_columns_are_not_nullable(inspector) -> None:
    """A set always carries a project, a name, a status and its JSON columns."""
    columns = {c["name"]: c for c in inspector.get_columns(SET_TABLE)}
    for name in ("project_id", "name", "status", "comparison_currency", "decision_criteria", "metadata"):
        assert columns[name]["nullable"] is False, name
    # The baseline is a soft pointer that may legitimately be unset.
    assert columns["baseline_option_id"]["nullable"] is True
    assert columns["created_by"]["nullable"] is True


def test_option_required_columns_are_not_nullable(inspector) -> None:
    """An option always carries its set, its project and its money columns."""
    columns = {c["name"]: c for c in inspector.get_columns(OPTION_TABLE)}
    for name in (
        "set_id",
        "project_id",
        "name",
        "sort_order",
        "status",
        "error",
        "direct_cost",
        "markups_total",
        "grand_total",
        "cost_per_m2",
        "gfa",
        "gfa_unit",
        "currency",
        "element_count",
        "position_count",
        "breakdown",
        "validation_status",
        "metadata",
    ):
        assert columns[name]["nullable"] is False, name
    # Source pairings are optional until the option is attached to something.
    for name in ("source_document_id", "bim_model_id", "boq_id", "match_session_id", "validation_score"):
        assert columns[name]["nullable"] is True, name


def test_set_project_foreign_key_cascades(inspector) -> None:
    """The set is deleted with its project (the only FK the set carries)."""
    fks = inspector.get_foreign_keys(SET_TABLE)
    assert len(fks) == 1
    fk = fks[0]
    assert fk["referred_table"] == "oe_projects_project"
    assert fk["constrained_columns"] == ["project_id"]
    assert fk["options"].get("ondelete") == "CASCADE"


def test_option_set_foreign_key_cascades_and_is_the_only_one(inspector) -> None:
    """The option's only FK is the same-module set link, cascading on delete.

    ``project_id`` is a denormalised copy for IDOR scoping and the cross-module
    pointers (document, BIM model, BOQ, match session) are plain GUIDs by the
    cross-module-reference convention, so none of them may be a foreign key.
    """
    fks = inspector.get_foreign_keys(OPTION_TABLE)
    assert len(fks) == 1
    fk = fks[0]
    assert fk["referred_table"] == SET_TABLE
    assert fk["constrained_columns"] == ["set_id"]
    assert fk["options"].get("ondelete") == "CASCADE"


def test_scoping_columns_are_indexed(inspector) -> None:
    """Every column the module filters or joins on carries an index."""
    set_indexed = {tuple(ix["column_names"]) for ix in inspector.get_indexes(SET_TABLE)}
    assert ("project_id",) in set_indexed

    option_indexed = {tuple(ix["column_names"]) for ix in inspector.get_indexes(OPTION_TABLE)}
    for column in ("set_id", "project_id", "bim_model_id", "boq_id"):
        assert (column,) in option_indexed, column


def test_neither_table_declares_a_unique_constraint(inspector) -> None:
    """Two options may share a name and a set may repeat inside a project."""
    assert inspector.get_unique_constraints(SET_TABLE) == []
    assert inspector.get_unique_constraints(OPTION_TABLE) == []


# ── Constraints enforced by the database ─────────────────────────────────────


async def test_option_without_a_set_is_rejected(session: AsyncSession) -> None:
    """``set_id`` is NOT NULL, so a free-floating option cannot be stored."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    session.add(DesignOption(set_id=None, project_id=project.id, name="Orphan"))  # type: ignore[arg-type]
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_option_pointing_at_a_missing_set_is_rejected(session: AsyncSession) -> None:
    """The set foreign key is enforced, not merely declared."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    session.add(DesignOption(set_id=uuid.uuid4(), project_id=project.id, name="Ghost"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_set_pointing_at_a_missing_project_is_rejected(session: AsyncSession) -> None:
    """The project foreign key is enforced, not merely declared."""
    session.add(DesignOptionSet(project_id=uuid.uuid4(), name="Ghost project"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_baseline_option_id_accepts_any_uuid(session: AsyncSession) -> None:
    """The baseline pointer is deliberately not a foreign key.

    A real FK would be circular (set -> option -> set), so the column is a plain
    GUID and referential integrity for it is the service layer's job.
    """
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id, baseline_option_id=uuid.uuid4())
    await session.flush()
    assert option_set.baseline_option_id is not None


# ── Relationship ─────────────────────────────────────────────────────────────


async def test_options_are_loaded_eagerly_and_ordered_by_sort_order(session: AsyncSession) -> None:
    """``set.options`` arrives populated and in sort order, not insertion order."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    await make_option(session, option_set, name="third", sort_order=2)
    await make_option(session, option_set, name="first", sort_order=0)
    await make_option(session, option_set, name="second", sort_order=1)
    await session.commit()
    session.expunge_all()

    fetched = await DesignOptionsService(session).get_set(option_set.id)
    # Reading the collection must not need a second query - the relationship is
    # selectin-loaded, which is what keeps the async router path safe.
    assert "options" not in sa_inspect(fetched).unloaded
    assert [o.name for o in fetched.options] == ["first", "second", "third"]


async def test_option_reaches_its_set_when_the_set_is_already_loaded(session: AsyncSession) -> None:
    """A child loaded through the set's collection can read ``option.set``.

    This is the half of the loading policy that must stay free: the parent is
    already in the session, so no SQL is needed. A strategy of ``lazy="raise"``
    fails here even though nothing would be queried, which is exactly why the
    policy asks for ``raise_on_sql``.
    """
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id, name="Frames")
    await make_option(session, option_set, name="Steel")
    await session.commit()
    session.expunge_all()

    fetched = await DesignOptionsService(session).get_set(option_set.id)
    child = fetched.options[0]
    assert child.set.id == option_set.id
    assert child.set.name == "Frames"


async def test_option_refuses_to_lazy_load_its_set_from_the_database(session: AsyncSession) -> None:
    """A child read on its own must not emit a stray query for its parent.

    With the set absent from the session, reading ``option.set`` would fire a
    lazy SELECT from an async context. The loading policy turns that into a
    named error at the point of touch instead of a ``MissingGreenlet`` further
    down the stack.
    """
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    await session.commit()
    session.expunge_all()

    lone = (await session.execute(select(DesignOption).where(DesignOption.id == option.id))).scalar_one()
    with pytest.raises(InvalidRequestError, match="DesignOption.set"):
        _ = lone.set


# ── Delete behaviour ─────────────────────────────────────────────────────────


async def test_orm_delete_of_a_set_removes_its_options(session: AsyncSession) -> None:
    """``session.delete(set)`` cascades through the ORM relationship."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    await make_option(session, option_set, name="A", sort_order=0)
    await make_option(session, option_set, name="B", sort_order=1)
    await session.commit()

    fetched = await DesignOptionsService(session).get_set(option_set.id)
    await session.delete(fetched)
    await session.commit()

    assert await _count(session, DesignOptionSet, id=option_set.id) == 0
    assert await _count(session, DesignOption, set_id=option_set.id) == 0


async def test_database_delete_of_a_set_row_cascades_to_its_options(session: AsyncSession) -> None:
    """The cascade is enforced by the database, not only by the ORM."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    await make_option(session, option_set, name="A")
    await session.commit()
    session.expunge_all()

    await session.execute(text(f"DELETE FROM {SET_TABLE} WHERE id = :sid"), {"sid": str(option_set.id)})
    await session.commit()

    assert await _count(session, DesignOption, set_id=option_set.id) == 0


async def test_database_delete_of_a_project_cascades_to_sets_and_options(session: AsyncSession) -> None:
    """Deleting the project takes the whole design-option graph with it."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    await make_option(session, option_set, name="A")
    await session.commit()
    session.expunge_all()

    await session.execute(text("DELETE FROM oe_projects_project WHERE id = :pid"), {"pid": str(project.id)})
    await session.commit()

    assert await _count(session, DesignOptionSet, id=option_set.id) == 0
    assert await _count(session, DesignOption, set_id=option_set.id) == 0


async def test_removing_an_option_from_the_collection_deletes_it(session: AsyncSession) -> None:
    """``delete-orphan`` deletes an option detached from its set."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    keep = await make_option(session, option_set, name="keep", sort_order=0)
    drop = await make_option(session, option_set, name="drop", sort_order=1)
    await session.commit()
    session.expunge_all()

    fetched = await DesignOptionsService(session).get_set(option_set.id)
    fetched.options.remove(next(o for o in fetched.options if o.id == drop.id))
    await session.commit()

    assert await _count(session, DesignOption, id=drop.id) == 0
    assert await _count(session, DesignOption, id=keep.id) == 1


async def test_deleting_one_option_leaves_the_set_and_its_siblings(session: AsyncSession) -> None:
    """Option deletion is not a cascade upwards."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    first = await make_option(session, option_set, name="A", sort_order=0)
    second = await make_option(session, option_set, name="B", sort_order=1)
    await session.commit()

    await DesignOptionsService(session).delete_option(first)
    await session.commit()

    assert await _count(session, DesignOptionSet, id=option_set.id) == 1
    assert await _count(session, DesignOption, id=first.id) == 0
    assert await _count(session, DesignOption, id=second.id) == 1
