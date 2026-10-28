# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Delete and restore every trash kind, through the endpoints, with real rows.

The recycle bin is polymorphic: one table holds a JSON snapshot of a row
belonging to any of eight kinds. Every existing test drove one half of that
loop - ``soft_delete`` with a synthetic payload, or ``restore`` from a
hand-written one - so nothing walked the round trip a user walks: delete a
real row, then press Restore.

That gap hid a defect. ``restore`` decided which snapshot values to convert
back out of JSON by the *name* of the key: anything ending in ``_id`` became
a ``UUID``, anything ending in ``_at`` or ``_date`` became a ``datetime``.
Ten columns across six of the eight kinds carry such a name on a ``String``
column, so the conversion handed a varchar an object it cannot store and the
insert failed inside ``flush`` with an asyncpg ``DataError``. A name is not a
type.

Two things follow for this file. It walks every kind, so the next model whose
column type disagrees with its key name is caught by the loop. And the seeded
rows deliberately fill every String column named the way the old rule keyed
off - :func:`test_the_seeds_fill_every_column_the_old_name_rule_would_convert`
fails if a new one appears unseeded, because a round trip that leaves the
dangerous columns NULL passes without ever touching the defect.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import String, Text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import GUID
from app.modules.file_trash.router import restore_trash
from app.modules.file_trash.router import soft_delete as soft_delete_endpoint
from app.modules.file_trash.schemas import TrashSoftDeleteRequest
from app.modules.file_trash.service import TRASH_KINDS, FileTrashService, _kind_model
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

# The suffixes the old restore rule keyed off. Kept here so the seed-coverage
# check keeps testing the real class of column even after the rule is gone.
_NAME_RULE_SUFFIXES = ("_id", "id", "_at", "_date", "date_")

# String columns named the way that rule keyed off, counted across the eight
# kinds. Pinned so the coverage check cannot pass by finding nothing.
_NAME_SHAPED_STRING_COLUMNS = 10


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as session:
        yield session


async def _seed_user_and_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"trash-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Trash Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Recycle Bin Suite", owner_id=user.id)
    session.add(project)
    await session.flush()
    return user.id, project.id


def _kind_kwargs(kind: str, *, project_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    """Column values for one row of ``kind``, as the product writes them.

    Beyond the NOT NULL columns each kind needs in order to exist, these fill
    the String columns whose names end in ``_id`` / ``_at`` / ``_date``. Those
    are optional on the model but they are the point of the exercise: left
    NULL, the round trip never reaches the conversion that broke.

    ``generated_at`` and ``author_id`` are written exactly as their own
    services write them - the reporting service stamps
    ``datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")`` and the markups
    service stores the acting user id as text - because the defect only bites
    when the value parses as the type its name suggests.
    """
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    soft_ref = str(uuid.uuid4())
    table: dict[str, dict] = {
        "document": {"project_id": project_id, "name": "site-plan.pdf"},
        "photo": {
            "project_id": project_id,
            "filename": "site.jpg",
            "file_path": "/uploads/site.jpg",
            "document_id": soft_ref,
        },
        "sheet": {
            "project_id": project_id,
            "page_number": 1,
            "document_id": soft_ref,
        },
        "bim_model": {
            "project_id": project_id,
            "name": "tower.ifc",
            "import_date": stamp,
            "original_file_id": soft_ref,
        },
        "dwg_drawing": {
            "project_id": project_id,
            "name": "Ground Floor",
            "filename": "plan.dwg",
            "file_path": "/uploads/plan.dwg",
        },
        "takeoff": {
            "project_id": project_id,
            "type": "area",
            "document_id": soft_ref,
            "linked_boq_position_id": soft_ref,
        },
        "report": {
            "project_id": project_id,
            "report_type": "cost_summary",
            "title": "Cost Summary",
            "generated_at": stamp,
        },
        "markup": {
            "project_id": project_id,
            "type": "rectangle",
            "author_id": str(user_id),
            "document_id": soft_ref,
            "linked_boq_position_id": soft_ref,
        },
    }
    if kind not in table:
        raise KeyError(f"no seed row defined for trash kind {kind!r}")
    return table[kind]


def test_every_kind_has_a_row_to_seed() -> None:
    """A ninth kind must arrive with a row here, or the sweep is a sample."""
    ids = uuid.uuid4()
    for kind in TRASH_KINDS:
        assert _kind_kwargs(kind, project_id=ids, user_id=ids), f"{kind}: seed row is empty"


def test_the_seeds_fill_every_column_the_old_name_rule_would_convert() -> None:
    """The dangerous columns must be populated or the round trip proves nothing.

    ``restore`` used to convert a value whenever its key ended in ``_id`` /
    ``_at`` / ``_date``, whatever the column's type was, and a String column
    named that way is where that broke. Leaving one NULL in the seed data
    would let the round trip pass over the defect without touching it, so
    this asserts the seeds cover the whole class.
    """
    ids = uuid.uuid4()
    unseeded: list[str] = []
    covered = 0
    for kind in TRASH_KINDS:
        seeded = _kind_kwargs(kind, project_id=ids, user_id=ids)
        for attr in _kind_model(kind).__mapper__.column_attrs:
            col = attr.columns[0]
            if isinstance(col.type, GUID) or not isinstance(col.type, (String, Text)):
                continue
            if not attr.key.endswith(_NAME_RULE_SUFFIXES):
                continue
            if attr.key in seeded:
                covered += 1
            else:
                unseeded.append(f"{kind}.{attr.key}")
    assert not unseeded, (
        "String column(s) named the way the old rule keyed off, left NULL by the "
        f"seed data: {', '.join(unseeded)}. Give each one a value so the round "
        "trip actually carries it through restore."
    )
    # Without this the check would also pass by matching nothing at all.
    assert covered == _NAME_SHAPED_STRING_COLUMNS, (
        f"expected {_NAME_SHAPED_STRING_COLUMNS} such columns, found {covered}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", TRASH_KINDS)
async def test_a_real_row_survives_delete_and_restore(
    kind: str,
    db_session: AsyncSession,
) -> None:
    """Delete a real row of ``kind`` from the file manager, then put it back.

    Both calls go through the router rather than the service, and the delete
    omits ``payload`` exactly as both front-end call sites do, so the path
    under test is the one a user's click takes.
    """
    user_id, project_id = await _seed_user_and_project(db_session)
    model = _kind_model(kind)
    seeded = _kind_kwargs(kind, project_id=project_id, user_id=user_id)
    original = model(**seeded)
    db_session.add(original)
    await db_session.flush()
    original_id = original.id

    service = FileTrashService(db_session)
    trashed = await soft_delete_endpoint(
        payload=TrashSoftDeleteRequest(
            project_id=project_id,
            kind=kind,
            original_id=str(original_id),
            canonical_name=f"{kind}.bin",
        ),
        session=db_session,
        user_id=str(user_id),
        service=service,
    )
    assert await db_session.get(model, original_id) is None, f"{kind}: the original row is still there"

    await restore_trash(
        trash_id=trashed.id,
        _body=None,
        session=db_session,
        user_id=str(user_id),
        service=service,
    )
    back = await db_session.get(model, original_id)
    assert back is not None, f"{kind}: restore reported success but the row is gone"
    # The snapshot has to survive the trip intact, not merely re-insert.
    for key, value in seeded.items():
        assert str(getattr(back, key)) == str(value), f"{kind}.{key} came back changed"
